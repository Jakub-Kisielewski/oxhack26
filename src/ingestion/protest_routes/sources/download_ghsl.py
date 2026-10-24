#!/usr/bin/env python3
"""Download one GHSL raster archive selected in the official GHSL wizard.

Example:
 python 05_download_ghsl.py --url 'https://jeodpp.jrc.ec.europa.eu/.../your-selected-product.zip'

The user must select a precise GHS-POP or GHS-BUILT-S tile/epoch/resolution
and paste its official download link. The tool does not guess a large global URL.
Output is a byte-exact source ZIP or TIFF, *not* pre-clipped London imagery.
"""
import argparse, pathlib, urllib.parse
import requests

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--url',required=True,help='Official HTTP(S) raster download URL from GHSL download wizard')
    p.add_argument('--output',default='raw/ghsl/selected_source.zip')
    a=p.parse_args()
    parsed=urllib.parse.urlparse(a.url)
    if parsed.scheme!='https': raise SystemExit('Use a HTTPS URL from the GHSL official website')
    dest=pathlib.Path(a.output);dest.parent.mkdir(parents=True,exist_ok=True)
    with requests.get(a.url,stream=True,timeout=(30,120)) as r:
        r.raise_for_status()
        with dest.open('wb') as f:
            for b in r.iter_content(chunk_size=1024*1024):
                if b:f.write(b)
    print('Saved',dest, 'bytes',dest.stat().st_size)

if __name__=='__main__': main()
