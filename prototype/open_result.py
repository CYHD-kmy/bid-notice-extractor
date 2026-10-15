"""Print the viewer URL for one saved run; does not invoke a model or server."""
import argparse
from pathlib import Path
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parents[1]

def viewer_url(path, port=8765):
    path=Path(path).resolve()
    relative=path.relative_to(ROOT)
    if relative.parts[0]!='outputs' or path.name!='result.json' or not path.is_file():
        raise ValueError('请选择项目 outputs 下存在的 result.json')
    if not 1<=port<=65535: raise ValueError('端口不合法')
    return f'http://127.0.0.1:{port}/prototype/web/index.html?'+urlencode({'result':relative.as_posix()})

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('result',type=Path)
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    try: print(viewer_url(args.result,args.port))
    except ValueError as error: parser.error(str(error))
