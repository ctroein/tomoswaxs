"""HTTP OME-Zarr: whole-chunk GETs for v2, native range reads for v3."""
from collections.abc import Mapping
import json
from pathlib import PurePosixPath

import ngff_zarr as ngff


class HttpV2Store(Mapping):
    """Public ngff-zarr bytes-mapping interface for GET-only Zarr v2 services.

    Only missing (404) objects become KeyError/fill values. HTTP errors must
    propagate. Array decoding, edge trimming and lazy Dask assembly stay in
    ngff-zarr; this adapter only transports complete objects and caches metadata.
    """
    def __init__(self,url):
        from obstore.store import HTTPStore
        self.url=url
        self._store=HTTPStore.from_url(url,client_options={'allow_http':True} if url.startswith('http:') else None)
        self._metadata={};self._keys=set()

    def __getitem__(self,key):
        import obstore
        if key in self._metadata:return self._metadata[key]
        try:data=bytes(obstore.get(self._store,key).bytes())
        except (FileNotFoundError,obstore.exceptions.NotFoundError):raise KeyError(key) from None
        if PurePosixPath(key).name in ('.zarray','.zattrs','.zgroup','.zmetadata','zarr.json'):
            self._metadata[key]=data;self._keys.add(key)
        return data

    def inventory(self):
        """List metadata nodes from the multiscale description, without a crawl."""
        try:
            consolidated=json.loads(self['.zmetadata']).get('metadata',{})
            if consolidated:
                self._keys.update(consolidated);return
        except KeyError:pass
        attrs=json.loads(self['.zattrs'])
        for scale in attrs.get('multiscales',[]):
            for dataset in scale.get('datasets',[]):
                path=dataset['path'].strip('/')
                self._keys.update((path+'/.zarray',path+'/.zattrs'))
                for parent in PurePosixPath(path).parents:
                    if str(parent)!='.':self._keys.add(str(parent)+'/.zgroup')

    def __iter__(self):return iter(tuple(self._keys))
    def __len__(self):return len(self._keys)


def read_http_multiscales(url):
    store=HttpV2Store(url)
    try:
        store['zarr.json']
    except KeyError:
        try:store['.zgroup']
        except KeyError:raise ValueError(f'No OME-Zarr image group was found at {url}') from None
        store.inventory()
        return ngff.from_ngff_zarr(store)
    # Sharded v3 needs byte ranges; use ngff-zarr's native remote backend.
    return ngff.from_ngff_zarr(url)
