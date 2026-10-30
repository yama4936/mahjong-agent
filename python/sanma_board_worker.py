"""Resident, read-only sanma image probe; one immutable image per JSON request."""
import base64
from hashlib import sha256
import json
import os
import sys
import tempfile
from pathlib import Path

print(json.dumps({'ready': True}), flush=True)
for line in sys.stdin:
    request_id = None
    filename = None
    try:
        request = json.loads(line)
        request_id = request.get('id')
        images = request.get('images')
        if type(request_id) is not int or not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], str):
            raise ValueError('one image and integer id required')
        frame = base64.b64decode(images[0], validate=True)
        if not frame or len(frame) > 20_000_000:
            raise ValueError('invalid image length')
        with tempfile.NamedTemporaryFile(prefix='jantama-sanma-worker-', suffix='.png', delete=False) as file:
            filename = file.name
            file.write(frame)
        from sanma_board_image import observe_sanma_image
        prediction = observe_sanma_image(Path(filename))
        prediction['frame_sha256'] = sha256(frame).hexdigest()
        print(json.dumps({'id': request_id, 'predictions': [prediction]}, ensure_ascii=False), flush=True)
    except Exception as error:
        print(json.dumps({'id': request_id, 'error': str(error)}, ensure_ascii=False), flush=True)
    finally:
        if filename:
            try:
                os.unlink(filename)
            except FileNotFoundError:
                pass
