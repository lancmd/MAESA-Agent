"""Stack LEAS per-class rasters into one CARS development-potential raster."""
from __future__ import annotations
import argparse
from pathlib import Path
import rasterio

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument('--directory',type=Path,required=True); p.add_argument('--output',type=Path,required=True); a=p.parse_args()
    files=[a.directory/f'development_potential_band_{i}.tif' for i in range(1,7)]
    if not all(f.is_file() for f in files): raise FileNotFoundError('LEAS band outputs are incomplete')
    with rasterio.open(files[0]) as src:
        profile=src.profile.copy(); profile.update(count=len(files),dtype=src.dtypes[0],compress='deflate',nodata=src.nodata)
        a.output.parent.mkdir(parents=True,exist_ok=True)
        with rasterio.open(a.output,'w',**profile) as dst:
            for index,f in enumerate(files,1):
                with rasterio.open(f) as band: dst.write(band.read(1),index)
    print(a.output)
    return 0
if __name__=='__main__': raise SystemExit(main())
