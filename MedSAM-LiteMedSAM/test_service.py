import urllib.request, json, io
from PIL import Image
import numpy as np

# 创建测试图
img = Image.fromarray(np.random.randint(50, 200, (512, 512, 3), dtype=np.uint8))
buf = io.BytesIO()
img.save(buf, 'PNG')
img_bytes = buf.getvalue()

# 构造 multipart/form-data
boundary = b'boundary123'
body = (
    b'--' + boundary + b'\r\n'
    b'Content-Disposition: form-data; name="sam_image"; filename="test.png"\r\n'
    b'Content-Type: image/png\r\n\r\n'
    + img_bytes +
    b'\r\n--' + boundary + b'--\r\n'
)
req = urllib.request.Request('http://localhost:8000/segment', data=body, method='POST')
req.add_header('Content-Type', 'multipart/form-data; boundary=boundary123')
r = urllib.request.urlopen(req)
result = json.loads(r.read())
print('响应:', result)
print('成功!' if result.get('success') else '失败!')
