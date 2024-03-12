import dominate

def test_version():
  assert dominate.version == dominate.__version__
  assert dominate.version
