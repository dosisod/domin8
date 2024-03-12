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

from typing import Any, List, Optional, Tuple, Union, cast, overload

from dominate.dom_tag import TagLike, TagLike_T
from . import tags
from . import util


class document(tags.html):
  tagname = 'html'

  title_node: Optional[tags.title]
  body: tags.body
  head: tags.head

  def __init__(self, title: Optional[str]='Dominate', doctype: Optional[str]='<!DOCTYPE html>', *a: Any, **kw: Any):
    '''
    Creates a new document instance. Accepts `title` and `doctype`
    '''
    super().__init__(*a, **kw)
    self.doctype    = doctype
    self.head       = super().add(tags.head())
    self.body       = super().add(tags.body())
    if title is None:
      self.title_node = None
    else:
      self.title_node = self.head.add(tags.title(title))
    with self.body:
      self.header   = util.container()
      self.main     = util.container()
      self.footer   = util.container()
    self._entry = self.main

  def get_title(self) -> str:
    return self.title_node.text if self.title_node else ''

  def set_title(self, title: Union[str, tags.title]) -> None:
    if isinstance(title, str):
      if self.title_node:
        self.title_node.text = title
      else:
        self.title_node = tags.title(title)
    else:
      if self.title:
        self.head.remove(self.title_node)
      self.head.add(title)
      self.title_node = title

  title = property(get_title, set_title)

  @overload
  def add(self, arg: TagLike_T, /) -> TagLike_T: ...  # type: ignore[overload-overlap]

  @overload
  def add(self, *args: TagLike) -> Tuple[TagLike, ...]: ...

  def add(self, *args: TagLike) -> Union[TagLike, Tuple[TagLike, ...]]:
    '''
    Adding tags to a document appends them to the <body>.
    '''
    return self._entry.add(*args)

  def _render(self, sb: List[str], *args: Any, **kwargs: Any) -> List[str]:
    '''
    Renders the DOCTYPE and tag tree.
    '''
    # adds the doctype if one was set
    if self.doctype:
      sb.write(self.doctype)
      sb.write('\n')
    super()._render(sb, *args, **kwargs)

  def __repr__(self) -> str:
    return '<dominate.document "%s">' % self.title
