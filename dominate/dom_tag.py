from __future__ import annotations
from typing_extensions import LiteralString, Self

__license__ = '''
This file is part of Dominate.

Dominate is free software: you can redistribute it and/or modify
it under the terms of the GNU Lesser General Public License as
published by the Free Software Foundation, either version 3 of
the License, or (at your option) any later version.

Dominate is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General
Public License along with Dominate.  If not, see
<http://www.gnu.org/licenses/>.
'''

# pylint: disable=bad-indentation, bad-whitespace, missing-docstring

import copy
import numbers
from io import StringIO
from collections import defaultdict
from functools import wraps
import threading
from asyncio import get_event_loop
from typing import TYPE_CHECKING, Any, DefaultDict, Dict, Iterator, List, NamedTuple, Optional, Set, Tuple, Type, TypeVar, Union, cast, overload
from uuid import uuid4
from contextvars import ContextVar


if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "TagLike",
    "TagLike_T",
    "attr",
    "dom_tag",
    "get_current",
    "util",
]


try:
  import greenlet  # type: ignore
except ImportError:
  greenlet = None

# We want dominate to work in async contexts - however, the problem is
# when we bind a tag using "with", we set what is essentially a global variable.
# If we are processing multiple documents at the same time, one context
# can "overwrite" the "bound tag" of another - this can cause documents to
# sort of bleed into one another...

# The solution is to use a ContextVar - which provides async context local storage.
# We use this to store a unique ID for each async context. We then use thie ID to
# form the key (in _get_thread_context) that is used to index the _with_context defaultdict.
# The presense of this key ensures that each async context has its own stack and doesn't conflict.
async_context_id: ContextVar[Optional[str]] = ContextVar('async_context_id', default=None)

def _get_async_context_id() -> str:
  if async_context_id.get() is None:
    async_context_id.set(uuid4().hex)
  return cast(str, async_context_id.get())

ThreadContext = Tuple[Union[threading.Thread, Any], ...]

def _get_thread_context() -> ThreadContext:
  context: List[Union[threading.Thread, Any]] = [threading.current_thread()]
  # Tag extra content information with a name to make sure
  # a greenlet.getcurrent() == 1 doesn't get confused with a
  # a _get_thread_context() == 1.
  if greenlet:
    context.append(("greenlet", greenlet.getcurrent()))

  try:
    if get_event_loop().is_running():
      # Only add this extra information if we are actually in a running event loop
      context.append(("async", _get_async_context_id()))
  # A runtime error is raised if there is no async loop...
  except RuntimeError:
    pass
  return tuple(context)

class Frame(NamedTuple):
  tag: "dom_tag"
  items: List["dom_tag"]
  used: Set["dom_tag"]

TagLike = Union["dom_tag", str, Dict[str, Any], numbers.Number, Any]
TagLike_T = TypeVar("TagLike_T", bound=TagLike)

T = TypeVar("T", "dom_tag", str)

class dom_tag:
  is_single = False  # Tag does not require matching end tag (ex. <hr/>)
  is_pretty = True   # Text inside the tag should be left as-is (ex. <pre>)
                     # otherwise, text will be escaped() and whitespace may be
                     # modified
  is_inline = False


  def __new__(_cls, *args: Any, **kwargs: Any) -> "dom_tag":
    '''
    Check if bare tag is being used a a decorator
    (called with a single function arg).
    decorate the function and return
    '''
    if len(args) == 1 and callable(args[0]) \
        and not isinstance(args[0], dom_tag) and not kwargs:
      wrapped = args[0]

      @wraps(wrapped)
      def f(*args: Any, **kwargs: Any) -> Any:
        with _cls() as _tag:
          return wrapped(*args, **kwargs) or _tag
      return f  # type: ignore
    return object.__new__(_cls)


  def __init__(self, *args: Any, **kwargs: Any) -> None:
    '''
    Creates a new tag. Child tags should be passed as arguments and attributes
    should be passed as keyword arguments.

    There is a non-rendering attribute which controls how the tag renders:

    * `__inline` - Boolean value. If True renders all children tags on the same
                   line.
    '''

    self.attributes: Dict[str, Union[str, bool, Any]] = {}
    self.children: List[Union[dom_tag, str]] = []
    self.parent: Optional[dom_tag] = None

    # Does not insert newlines on all children if True (recursive attribute)
    self.is_inline = kwargs.pop('__inline', self.is_inline)
    self.is_pretty = kwargs.pop('__pretty', self.is_pretty)

    #Add child elements
    if args:
      self.add(*args)

    for attr, value in kwargs.items():
      self.set_attribute(*type(self).clean_pair(attr, value))

    self._ctx: Optional[Frame] = None
    self._add_to_ctx()


  # stack of frames
  _with_contexts: DefaultDict[ThreadContext, List[Frame]] = defaultdict(list)

  def _add_to_ctx(self) -> None:
    stack = dom_tag._with_contexts.get(_get_thread_context())
    if stack:
      self._ctx = stack[-1]
      stack[-1].items.append(self)


  def __enter__(self) -> dom_tag:
    stack = dom_tag._with_contexts[_get_thread_context()]
    stack.append(Frame(self, [], set()))
    return self


  def __exit__(self, type: Any, value: Any, traceback: Any) -> None:
    thread_id = _get_thread_context()
    stack = dom_tag._with_contexts[thread_id]
    frame = stack.pop()
    for item in frame.items:
      if item in frame.used: continue
      self.add(item)
    if not stack:
      del dom_tag._with_contexts[thread_id]


  def __call__(self, func: Callable[..., Any]) -> Callable[..., dom_tag]:
    '''
    tag instance is being used as a decorator.
    wrap func to make a copy of this tag
    '''
    # remove decorator from its context so it doesn't
    # get added in where it was defined
    if self._ctx:
      self._ctx.used.add(self)

    @wraps(func)
    def f(*args: Any, **kwargs: Any) -> dom_tag:
      tag = copy.deepcopy(self)
      tag._add_to_ctx()
      with tag:
        return func(*args, **kwargs) or tag
    return f


  def set_attribute(self, key: Union[int, str], value: Any) -> None:
    '''
    Add or update the value of an attribute.
    '''
    if isinstance(key, int):
      self.children[key] = value
    elif isinstance(key, str):
      self.attributes[key] = value
    else:
      raise TypeError('Only integer and string types are valid for assigning '
          'child tags and attributes, respectively.')
  __setitem__ = set_attribute


  def delete_attribute(self, key: Union[int, str]) -> None:
    if isinstance(key, int):
      del self.children[key:key+1]
    else:
      del self.attributes[key]
  __delitem__ = delete_attribute

  @overload
  def add(self, arg: TagLike_T, /) -> TagLike_T: ...  # type: ignore[overload-overlap]

  @overload
  def add(self, *args: TagLike) -> Tuple[TagLike, ...]: ...

  def add(self, *args: TagLike) -> Union[TagLike, Tuple[TagLike, ...]]:
    '''
    Add new child tags.
    '''
    for obj in args:
      if isinstance(obj, numbers.Number):
        # Convert to string so we fall into next if block
        obj = str(obj)

      if isinstance(obj, str):
        obj = util.escape(obj)
        self.children.append(obj)

      elif isinstance(obj, dom_tag):
        stack = dom_tag._with_contexts.get(_get_thread_context(), [])
        for s in stack:
          s.used.add(obj)
        self.children.append(obj)
        obj.parent = self

      elif isinstance(obj, dict):
        for attr, value in obj.items():
          self.set_attribute(*dom_tag.clean_pair(attr, value))

      elif hasattr(obj, '__iter__'):
        for subobj in obj:
          self.add(subobj)

      else:  # wtf is it?
        raise ValueError('%r not a tag or string.' % obj)

    if len(args) == 1:
      return args[0]

    return args


  def add_raw_string(self, s: LiteralString) -> None:
    self.children.append(s)


  def remove(self, obj: Any) -> None:
    self.children.remove(obj)


  def clear(self) -> None:
    for i in self.children:
      if isinstance(i, dom_tag) and i.parent is self:
        i.parent = None
    self.children = []


  def get(self, tag: Optional[Type[T]]=None, **kwargs: Any) -> List[T]:
    '''
    Recursively searches children for tags of a certain
    type with matching attributes.
    '''
    # Stupid workaround since we can not use dom_tag in the method declaration
    if tag is None:
      tag = cast(Type[T], dom_tag)

    attrs = [(dom_tag.clean_attribute(attr), value)
        for attr, value in kwargs.items()]

    results = []
    for child in self.children:
      if (isinstance(tag, str) and type(child).__name__ == tag) or \
        (not isinstance(tag, str) and isinstance(child, tag)):

        if all(child.attributes.get(attribute) == value  # type: ignore
            for attribute, value in attrs):
          # If the child is of correct type and has all attributes and values
          # in kwargs add as a result
          results.append(child)
      if isinstance(child, dom_tag):
        # If the child is a dom_tag extend the search down through its children
        results.extend(child.get(tag, **kwargs))
    return results


  def __getitem__(self, key: Union[str, int]) -> Union[dom_tag, str, bool, Any]:
    '''
    Returns the stored value of the specified attribute or child
    (if it exists).
    '''
    if isinstance(key, int):
      # Children are accessed using integers
      try:
        return object.__getattribute__(self, 'children')[key]
      except IndexError:
        raise IndexError('Child with index "%s" does not exist.' % key)
    elif isinstance(key, str):
      # Attributes are accessed using strings
      try:
        return object.__getattribute__(self, 'attributes')[key]
      except KeyError:
        raise AttributeError('Attribute "%s" does not exist.' % key)
    else:
      raise TypeError('Only integer and string types are valid for accessing '
          'child tags and attributes, respectively.')
  __getattr__ = __getitem__


  def __len__(self) -> int:
    '''
    Number of child elements.
    '''
    return len(self.children)


  def __bool__(self) -> bool:
    '''
    Hack for "if x" and __len__
    '''
    return True


  def __iter__(self) -> Iterator[dom_tag | str]:
    '''
    Iterates over child elements.
    '''
    return self.children.__iter__()


  def __contains__(self, item: Type[T]) -> bool:
    '''
    Checks recursively if item is in children tree.
    Accepts both a string and a class.
    '''
    return bool(self.get(item))


  def __iadd__(self, obj: TagLike) -> Self:
    '''
    Reflexive binary addition simply adds tag as a child.
    '''
    self.add(obj)
    return self

  def __str__(self) -> str:
    return self.render()


  def render(self, indent: str='  ', pretty: bool=True, xhtml: bool=False):
    sb = StringIO()
    self._render(sb, 0, indent, pretty, xhtml)
    return sb.getvalue()


  def _render(self, sb: StringIO, indent_level: int, indent_str: str, pretty: bool, xhtml: bool) -> StringIO:
    pretty = pretty and self.is_pretty

    name = getattr(self, 'tagname', type(self).__name__)

    # Workaround for python keywords and standard classes/methods
    # (del, object, input)
    if name[-1] == '_':
      name = name[:-1]

    # open tag
    sb.write('<')
    sb.write(name)

    for attribute, value in sorted(self.attributes.items()):
      if value in (False, None):
        continue
      if value is True:
        sb.write(f' {attribute}')
      else:
        val = str(value) if isinstance(value, util.text) and not value.escape else util.escape(str(value), True)
        sb.write(' %s="%s"' % (attribute, val))

    sb.write(' />' if self.is_single and xhtml else '>')

    if self.is_single:
      return sb

    inline = self._render_children(sb, indent_level + 1, indent_str, pretty, xhtml)
    if pretty and not inline:
      sb.write('\n')
      sb.write(indent_str * indent_level)

    # close tag
    sb.write('</')
    sb.write(name)
    sb.write('>')

    return sb

  def _render_children(self, sb: StringIO, indent_level: int, indent_str: str, pretty: bool, xhtml: bool) -> bool:
    inline = True
    for child in self.children:
      if isinstance(child, dom_tag):
        if pretty and not child.is_inline:
          inline = False
          sb.write('\n')
          sb.write(indent_str * indent_level)
        child._render(sb, indent_level, indent_str, pretty, xhtml)
      else:
        sb.write(str(child))

    return inline


  def __repr__(self) -> str:
    name = '%s.%s' % (self.__module__, type(self).__name__)

    attributes_len = len(self.attributes)
    attributes = '%s attribute' % attributes_len
    if attributes_len != 1: attributes += 's'

    children_len = len(self.children)
    children = '%s child' % children_len
    if children_len != 1: children += 'ren'

    return '<%s at %x: %s, %s>' % (name, id(self), attributes, children)


  @staticmethod
  def clean_attribute(attribute: str) -> str:
    '''
    Normalize attribute names for shorthand and work arounds for limitations
    in Python's syntax
    '''

    # Shorthand
    attribute = {
      'cls': 'class',
      'className': 'class',
      'class_name': 'class',
      'klass': 'class',
      'fr': 'for',
      'html_for': 'for',
      'htmlFor': 'for',
      'phor': 'for',
    }.get(attribute, attribute)

    # Special case to support Hyperscript
    if attribute == '_':
        pass

    # Workaround for Python's reserved words
    elif attribute[0] == '_':
      attribute = attribute[1:]

    # Workaround for colon
    elif attribute.split('_')[0] in ('xlink', 'xml', 'xmlns'):
      attribute = attribute.replace('_', ':', 1).lower()

    # Workaround for dash
    else:
        attribute = attribute.replace('_', '-')

    return attribute


  @classmethod
  def clean_pair(cls, attribute: str, value: Union[str, bool, Any]) -> tuple[str, Union[str, bool, Any]]:
    '''
    This will call `clean_attribute` on the attribute and also allows for the
    creation of boolean attributes.

    Ex. input(selected=True) is equivalent to input(selected="selected")
    '''
    attribute = cls.clean_attribute(attribute)

    # HTML has some boolean like attributes that can be true/false or on/off. Having to
    # rember which attributes have which naming conventions is annoying, so being able to
    # use True/False makes it so I don't have to remember.
    if isinstance(value, bool):
        if attribute in {'autocapitalize', 'autocomplete'}:
            value = "on" if value else "off"

        if attribute in {'contenteditable', 'draggable', 'spellcheck', 'translate'}:
            value = "true" if value else "false"

    # Ignore `if value is False`: this is filtered out in render()

    return (attribute, value)


_get_current_none = object()
def get_current(default: Any=_get_current_none) -> Union[dom_tag, Any]:
  '''
  get the current tag being used as a with context or decorated function.
  if no context is active, raises ValueError, or returns the default, if provided
  '''
  h = _get_thread_context()
  ctx = dom_tag._with_contexts.get(h, None)
  if ctx:
    return ctx[-1].tag
  if default is _get_current_none:
    raise ValueError('no current context')
  return default


def attr(*args: Dict[str, Any], **kwargs: Any) -> None:
  '''
  Set attributes on the current active tag context
  '''
  c = get_current()
  dicts = args + (kwargs,)
  for d in dicts:
    for attr, value in d.items():
      c.set_attribute(*dom_tag.clean_pair(attr, value))


from . import util
