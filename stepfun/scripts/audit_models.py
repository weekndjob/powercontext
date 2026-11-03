"""Read initializer storage types from the three pinned, self-contained ONNX files.

This small protobuf wire reader only audits the fixed ModelProto/GraphProto/
TensorProto fields used here. It does not execute or modify the graph.
"""
from pathlib import Path
from collections import Counter
import json

def varint(buffer, position):
    value = shift = 0
    while True:
        byte = buffer[position]
        position += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, position
        shift += 7

def fields(buffer):
    position = 0
    while position < len(buffer):
        tag, position = varint(buffer, position)
        number, wire = tag >> 3, tag & 7
        if wire == 0:
            value, position = varint(buffer, position)
        elif wire == 2:
            size, position = varint(buffer, position)
            value = buffer[position:position + size]
            position += size
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            value = buffer[position:position + size]
            position += size
        else:
            raise ValueError(f"Unsupported ONNX protobuf wire type: {wire}")
        yield number, wire, value

result = {}
root = Path(__file__).resolve().parents[1]
for filename in ['model.onnx', 'model_fp16.onnx', 'model_quantized.onnx']:
    buffer = memoryview((root / 'public/models/Xenova/all-MiniLM-L6-v2/onnx' / filename).read_bytes())
    graph = next(value for number, _, value in fields(buffer) if number == 7)
    counter, examples = Counter(), {}
    for number, _, tensor in fields(graph):
        if number != 5:
            continue
        items = list(fields(tensor))
        dtype = next((value for key, _, value in items if key == 2), 0)
        name = next((bytes(value).decode() for key, _, value in items if key == 8), '')
        counter[dtype] += sum(len(value) for key, _, value in items if key == 9)
        examples.setdefault(dtype, name)
    result[filename] = {'initializerRawBytesByDataType': dict(counter), 'exampleInitializerByType': examples}
(root / 'artifacts').mkdir(exist_ok=True)
(root / 'artifacts/onnx-weight-audit.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result, indent=2))
