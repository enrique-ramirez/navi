# agitha page

React on Vite. `pnpm install`, then `pnpm dev` serves it on port 8124 and proxies `/api` to `http://localhost:8882`, or to `AGITHA_URL` where that is set.

To run a local server against temporary folders, with the stub engine, which works offline (the real `musiclib` command needs the box):

```sh
cd hyrule-castle/music
../../_tmp/venv/bin/python -m agitha --host 127.0.0.1 --port 8882 \
    --inbox <dir> --jobs <dir> --library <dir> --extras <dir> \
    --musiclib tests/agitha_stub.py --static agitha/ui/dist
```
