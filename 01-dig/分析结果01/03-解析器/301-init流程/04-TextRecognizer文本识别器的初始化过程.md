# TextRecognizer文本识别器的初始化过程

## 类定义位置
- 文件：`deepdoc/vision/ocr.py`
- 行号：133行开始 `class TextRecognizer:`

## 初始化方法 (__init__)

### 方法签名
```python
def __init__(self, model_dir, device_id: int | None = None):
```

### 初始化步骤

1. **设置图像形状参数**
   ```python
   self.rec_image_shape = [int(v) for v in "3, 48, 320".split(",")]
   ```
   - 设置默认图像形状为 [3, 48, 320] (通道数, 高度, 宽度)

2. **设置批处理参数**
   ```python
   self.rec_batch_num = 16
   ```
   - 设置批处理数量为16，用于批量处理图像识别

3. **构建后处理操作**
   ```python
   postprocess_params = {
       'name': 'CTCLabelDecode',
       "character_dict_path": os.path.join(model_dir, "ocr.res"),
       "use_space_char": True
   }
   self.postprocess_op = build_post_process(postprocess_params)
   ```
   - 创建CTC标签解码器
   - 指定字符字典文件路径为 `model_dir/ocr.res`
   - 启用空格字符识别

4. **加载识别模型**
   ```python
   self.predictor, self.run_options = load_model(model_dir, 'rec', device_id)
   ```
   - 调用 `load_model` 函数加载识别模型 (rec.onnx)
   - 根据 `device_id` 参数决定使用GPU还是CPU
   - 将模型预测器和运行选项保存为实例属性

5. **获取输入张量**
   ```python
   self.input_tensor = self.predictor.get_inputs()[0]
   ```
   - 获取模型的第一个输入张量，用于后续的图像预处理

## 设计特点
- TextRecognizer负责OCR流程中的文本识别阶段
- 支持GPU/CPU设备选择
- 采用批处理方式提高识别效率
- 集成多种图像预处理和后处理方法