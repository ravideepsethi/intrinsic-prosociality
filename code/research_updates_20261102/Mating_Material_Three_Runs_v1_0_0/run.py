from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent/'code'))
from retained_pipeline import main
if __name__=='__main__':raise SystemExit(main())
