import dominate
from dominate.tags import *
from dominate import util


def test_context():
  id1 = dominate.dom_tag._get_thread_context()
  id2 = dominate.dom_tag._get_thread_context()
  assert id1 == id2

def test_include():
  import os
  try:
    f = open('_test_include.deleteme', 'w')
    f.write('Hello World')
    f.close()

    d = div()
    d += util.include('_test_include.deleteme')
    assert d.render() == '<div>Hello World</div>'

  finally:
    try:
      os.remove('_test_include.deleteme')
    except:
      pass


def test_unescape():
  assert util.unescape('&amp;&lt;&gt;&#32;') == '&<> '


def test_url():
  assert util.url_escape('hi there?') == 'hi%20there%3F'
  assert util.url_unescape('hi%20there%3f') == 'hi there?'


def test_container():
  d = div()
  with d:
    with util.container():
      pass
  assert d.render() == '<div></div>'


  d = div()
  with d:
    with util.container():
      h1('a')
  assert d.render() == \
'''<div>
  <h1>a</h1>
</div>'''
