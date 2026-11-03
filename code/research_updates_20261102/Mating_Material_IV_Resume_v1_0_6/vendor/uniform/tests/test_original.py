import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'original/tests'))
from test_uniform90 import TemporalTests, SelectionTests, ModelTests
