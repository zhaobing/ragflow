# TextDetector与TextRecognizer的职责和功能

## 一、概述

在OCR系统中，**TextDetector（文本检测器）**和**TextRecognizer（文本识别器）**是两个独立但协同工作的核心组件。它们遵循"先检测，后识别"（Detection-First）的设计理念，将复杂的OCR任务分解为两个阶段。

```
输入图像
    ↓
┌──────────────────┐
│  TextDetector    │  ← 第一阶段：定位文本位置
│  (文本在哪里？)   │
└──────────────────┘
    ↓ 文本框坐标
┌──────────────────┐
│  TextRecognizer  │  ← 第二阶段：识别文本内容
│  (文本是什么？)   │
└──────────────────┘
    ↓
文本字符串
```

## 二、TextDetector：文本检测器

### 2.1 核心职责

**回答问题：文本在图像的什么位置？**

TextDetector负责在整幅图像中**定位所有文本区域**，但不关心文本的具体内容。

### 2.2 主要功能

#### A. 文本区域定位

**输入**：原始图像（任意尺寸）
**输出**：文本框坐标列表 `List[np.ndarray]`，每个框的形状为 `(4, 2)`

```python
# 输出示例
dt_boxes = [
    [[x1, y1], [x2, y2], [x3, y3], [x4, y4]],  # 文本框1：四边形坐标
    [[x1, y1], [x2, y2], [x3, y3], [x4, y4]],  # 文本框2
    ...
]
```

**坐标顺序**：顺时针方向
- `[0]`: 左上角
- `[1]`: 右上角
- `[2]`: 右下角
- `[3]`: 左下角

#### B. 处理流程（[ocr.py:544-571](../../../../../deepdoc/vision/ocr.py#L544-L571)）

```python
def __call__(self, img):
    # 1. 保存原始图像
    ori_im = img.copy()

    # 2. 预处理
    data = transform(data, self.preprocess_op)
    #    - 缩放到960像素（最长边）
    #    - ImageNet归一化
    #    - HWC → CHW转换

    # 3. DBNet推理
    outputs = self.predictor.run(None, input_dict, self.run_options)
    #    输出: 概率图 + 阈值图

    # 4. 可微二值化后处理
    post_result = self.postprocess_op({"maps": outputs[0]}, shape_list)
    #    - 可微二值化
    #    - 轮廓查找
    #    - 四边形拟合

    # 5. 结果过滤
    dt_boxes = self.filter_tag_det_res(dt_boxes, ori_im.shape)
    #    - 过滤小尺寸框（宽或高<3像素）
    #    - 裁剪到图像边界
    #    - 顺时针排序坐标

    return dt_boxes, time.time() - st
```

#### C. 关键技术特点

| 特性 | 实现方式 | 作用 |
|------|---------|------|
| **多尺度检测** | FPN（特征金字塔） | 同时检测大文本和小文本 |
| **可微二值化** | DB算法 | 自适应阈值，端到端训练 |
| **四边形拟合** | DBPostProcess | 支持倾斜、弯曲文本 |
| **小框过滤** | `rect_width <= 3` | 去除噪声，提升精度 |

### 2.3 配置参数（[ocr.py:435-492](../../../../../deepdoc/vision/ocr.py#L435-L492)）

```python
# 预处理配置
pre_process_list = [{
    'DetResizeForTest': {
        'limit_side_len': 960,    # 最大边长（像素）
        'limit_type': "max",       # 限制最长边
    }
}, {
    'NormalizeImage': {
        'std': [0.229, 0.224, 0.225],
        'mean': [0.485, 0.456, 0.406],
        'scale': '1./255.',
        'order': 'hwc'
    }
}]

# 后处理配置
postprocess_params = {
    "name": "DBPostProcess",
    "thresh": 0.3,               # 二值化阈值
    "box_thresh": 0.5,           # 文本框置信度阈值
    "max_candidates": 1000,      # 最大候选框数量
    "unclip_ratio": 1.5,         # 文本框扩展比例
    "use_dilation": False,       # 是否使用膨胀
    "score_mode": "fast",        # 评分模式
    "box_type": "quad"           # 边界框类型（四边形）
}
```

### 2.4 典型应用场景

```
场景1: 扫描文档
输入: A4扫描件（2000×2830像素）
输出: 50个文本框（标题、段落、表格等）

场景2: 自然场景照片
输入: 街头招牌照片
输出: 3个倾斜文本框（招牌文字）

场景3: 复杂文档
输入: 多栏学术论文
输出: 100+个文本框（分栏、公式、图表说明）
```

### 2.5 性能指标

- **精度**: 召回率高，漏检少
- **速度**: 单张图像约50-200ms（GPU）
- **鲁棒性**: 支持旋转、模糊、低光照

---

## 三、TextRecognizer：文本识别器

### 3.1 核心职责

**回答问题：文本框中的内容是什么？**

TextRecognizer负责**识别文本区域中的具体文字内容**，将图像像素转换为可读的字符串。

### 3.2 主要功能

#### A. 文本内容识别

**输入**：裁剪后的文本图像列表 `List[np.ndarray]`
**输出**：识别结果列表 `List[Tuple[str, float]]`

```python
# 输出示例
rec_res = [
    ("Hello World", 0.98),      # (文本字符串, 置信度)
    ("人工智能", 0.95),
    ("123.45", 0.87),
    ...
]
```

#### B. 处理流程（[ocr.py:372-417](../../../../../deepdoc/vision/ocr.py#L372-L417)）

```python
def __call__(self, img_list):
    img_num = len(img_list)

    # 1. 按宽高比排序（优化批处理）
    width_list = [img.shape[1] / img.shape[0] for img in img_list]
    indices = np.argsort(np.array(width_list))

    # 2. 批量处理（batch_size=16）
    for beg_img_no in range(0, img_num, batch_num):
        # 2.1 计算batch中的最大宽高比
        max_wh_ratio = max([w/h for img in batch])

        # 2.2 预处理（resize + normalize + padding）
        for img in batch:
            norm_img = self.resize_norm_img(img, max_wh_ratio)
            #    - 缩放到高度48像素
            #    - 保持宽高比
            #    - 归一化到[-1, 1]
            #    - 右侧填充到统一宽度
            norm_img_batch.append(norm_img)

        # 2.3 CRNN推理（批量）
        outputs = self.predictor.run(None, input_dict, self.run_options)
        #    CNN特征提取 → BiLSTM序列建模 → CTC解码

        # 2.4 后处理
        rec_result = self.postprocess_op(preds)
        #    - CTC去重
        #    - 移除blank字符
        #    - 添加空格识别

    # 3. 恢复原始顺序
    return rec_res, time.time() - st
```

#### C. 关键技术特点

| 特性 | 实现方式 | 作用 |
|------|---------|------|
| **批处理优化** | `rec_batch_num=16` | 提升吞吐量 |
| **宽高比排序** | `np.argsort(width_list)` | 减少填充，加速计算 |
| **序列建模** | BiLSTM | 捕获字符上下文 |
| **CTC解码** | CTCLabelDecode | 处理不定长序列 |

### 3.3 预处理详解（[ocr.py:155-179](../../../../../deepdoc/vision/ocr.py#L155-L179)）

```python
def resize_norm_img(self, img, max_wh_ratio):
    imgC, imgH, imgW = [3, 48, 320]  # 通道、高度、宽度

    # 1. 计算目标宽度（保持宽高比）
    h, w = img.shape[:2]
    ratio = w / float(h)
    resized_w = min(int(math.ceil(imgH * ratio)), imgW)

    # 2. 缩放图像
    resized_image = cv2.resize(img, (resized_w, imgH))

    # 3. 归一化到[-1, 1]
    resized_image = resized_image.astype('float32') / 255
    resized_image = resized_image.transpose((2, 0, 1))  # HWC → CHW
    resized_image -= 0.5
    resized_image /= 0.5

    # 4. 右侧填充到固定宽度
    padding_im = np.zeros((imgC, imgH, imgW), dtype=np.float32)
    padding_im[:, :, 0:resized_w] = resized_image

    return padding_im
```

**关键点**：
- **固定高度48像素**：大多数文本行高度相似
- **可变宽度**：保持原始宽高比，最大320像素
- **右侧填充**：短文本右侧补零，确保批处理一致性

### 3.4 配置参数（[ocr.py:143-153](../../../../../deepdoc/vision/ocr.py#L143-L153)）

```python
class TextRecognizer:
    def __init__(self, model_dir, device_id):
        # 输入图像形状 [通道, 高度, 宽度]
        self.rec_image_shape = [3, 48, 320]

        # 批处理大小
        self.rec_batch_num = 16

        # CTC解码配置
        postprocess_params = {
            'name': 'CTCLabelDecode',
            'character_dict_path': 'ocr.res',  # 字符字典文件
            'use_space_char': True             # 识别空格
        }
```

### 3.5 批处理优化策略

#### 为什么需要排序？

```python
# 假设有3个文本框
box1: 100×20  (宽高比=5.0)
box2: 100×50  (宽高比=2.0)
box3: 50×20   (宽高比=2.5)

# 未排序的批处理（以最大宽高比5.0为准）
box1: 填充 100×48 → 100×48 (无填充)    ✅
box2: 填充 96×48 → 240×48 (大量填充)  ❌ 浪费计算
box3: 填充 48×48 → 240×48 (大量填充)  ❌ 浪费计算

# 排序后的批处理（box2, box3一组，box1单独）
batch1 (max_ratio=2.5):
  box2: 96×48 → 115×48 (少量填充)   ✅
  box3: 48×48 → 115×48 (少量填充)   ✅

batch2 (max_ratio=5.0):
  box1: 100×48 → 240×48 (单独处理)   ✅
```

**优化效果**：
- 减少填充比例，提升GPU利用率
- 相似尺寸的图像一起处理，计算效率更高

### 3.6 典型应用场景

```
场景1: 横排文本
输入: 裁剪后的英文句子图像
输出: "The quick brown fox" (置信度: 0.96)

场景2: 竖排文本
输入: 裁剪后的中文竖排文字
输出: "人工智能技术" (置信度: 0.92)

场景3: 数字识别
输入: 表格中的数字单元格
输出: "123.45" (置信度: 0.89)
```

### 3.7 性能指标

- **精度**: 字符准确率>95%，整词准确率>90%
- **速度**: 批处理16张图像约50-100ms（GPU）
- **鲁棒性**: 支持模糊、倾斜、低分辨率

---

## 四、两者协作关系

### 4.1 数据流向

```
原始图像（1920×1080）
    ↓
┌─────────────────────────────┐
│  TextDetector               │
│  - 检测到10个文本框          │
│  - 输出坐标: [(x1,y1),...]  │
└─────────────────────────────┘
    ↓ dt_boxes (列表，10个框)
┌─────────────────────────────┐
│  裁剪与矫正                  │
│  - 根据坐标裁剪图像          │
│  - 透视变换矫正倾斜          │
└─────────────────────────────┘
    ↓ img_crop_list (列表，10张图像)
┌─────────────────────────────┐
│  TextRecognizer             │
│  - 批量识别文本内容          │
│  - batch_size=16            │
└─────────────────────────────┘
    ↓ rec_res (列表，10个结果)
最终输出: [((box1), "文本1", 0.95), ...]
```

### 4.2 在OCR类中的协同（[ocr.py:753-796](../../../../../deepdoc/vision/ocr.py#L753-L796)）

```python
class OCR:
    def __call__(self, img, device_id=0, cls=True):
        # 阶段1: 文本检测
        dt_boxes, elapse = self.text_detector[device_id](img)
        # 输出: 10个文本框

        if dt_boxes is None:
            return None, None, time_dict

        # 阶段2: 图像裁剪
        img_crop_list = []
        dt_boxes = self.sorted_boxes(dt_boxes)  # 按位置排序

        for box in dt_boxes:
            img_crop = self.get_rotate_crop_image(ori_im, box)
            # 根据四边形坐标裁剪并矫正
            img_crop_list.append(img_crop)

        # 阶段3: 文本识别（批处理）
        rec_res, elapse = self.text_recognizer[device_id](img_crop_list)
        # 输入: 10张裁剪图像
        # 输出: 10个(文本, 置信度)对

        # 阶段4: 结果过滤和组合
        filter_boxes, filter_rec_res = [], []
        for box, rec_result in zip(dt_boxes, rec_res):
            text, score = rec_result
            if score >= self.drop_score:  # 0.5
                filter_boxes.append(box)
                filter_rec_res.append(rec_result)

        return list(zip([a.tolist() for a in filter_boxes], filter_rec_res))
```

### 4.3 职责边界

| 方面 | TextDetector | TextRecognizer |
|------|-------------|----------------|
| **输入** | 整幅图像 | 裁剪后的文本区域 |
| **输出** | 文本框坐标 | 文本字符串 |
| **关注点** | **位置**：文本在哪里 | **内容**：文本是什么 |
| **处理单元** | 像素级分割 | 字符级识别 |
| **算法** | DBNet（分割） | CRNN+CTC（序列） |
| **独立性** | 可单独使用 | 依赖检测结果 |
| **失败影响** | 漏检文本 | 识别错误 |

---

## 五、设计优势

### 5.1 模块化设计

**优势**：
- **独立优化**：检测和识别模型可以独立训练和优化
- **灵活替换**：可以升级识别器而不影响检测器
- **并行处理**：检测和识别可以在不同设备上运行

### 5.2 分而治之

**问题**：直接端到端识别整幅图像中的所有文本
- 计算量大
- 需要字符级标注
- 难以处理多尺度文本

**解决方案**：分解为两个子任务
1. **检测**：粗粒度定位（像素级分割）
2. **识别**：细粒度识别（字符级分类）

### 5.3 性能优化

**TextDetector优化**：
- 图像金字塔（FPN）：多尺度特征融合
- 可微二值化：简化后处理
- 单次推理：处理整幅图像

**TextRecognizer优化**：
- 批处理：一次识别多个文本框
- 宽高比排序：减少填充
- 固定高度：简化计算

---

## 六、实际应用示例

### 6.1 扫描文档OCR

```python
# 输入：扫描的PDF页面
image = cv2.imread('page_001.jpg')  # 2000×2830像素

# 步骤1：文本检测
dt_boxes = text_detector(image)
# 检测到50个文本框（标题、段落、表格等）

# 步骤2：文本识别
img_crop_list = [crop_image(image, box) for box in dt_boxes]
texts = text_recognizer(img_crop_list)

# 输出
results = [
    (box1, "第一章 引言", 0.98),
    (box2, "本文介绍OCR的基本原理...", 0.95),
    (box3, "表1-1 性能对比", 0.93),
    ...
]
```

### 6.2 场景文字识别

```python
# 输入：街头招牌照片
image = cv2.imread('street_sign.jpg')  # 1920×1080像素

# 文本检测
dt_boxes = text_detector(image)
# 检测到3个倾斜文本框

# 文本识别
texts = text_recognizer([crop_image(image, box) for box in dt_boxes])

# 输出
[
    (box1, "咖啡店", 0.92),
    (box2, "营业时间: 9:00-22:00", 0.89),
    (box3, "欢迎光临", 0.95)
]
```

---

## 七、总结

### 7.1 核心区别

| 维度 | TextDetector | TextRecognizer |
|------|-------------|----------------|
| **本质问题** | 文本在哪里？ | 文本是什么？ |
| **输入尺寸** | 任意（整幅图像） | 固定（裁剪区域） |
| **输出类型** | 坐标（连续值） | 字符串（离散值） |
| **技术路线** | 计算机视觉（分割） | 序列建模（NLP） |
| **处理方式** | 单次推理 | 批量推理 |

### 7.2 协同价值

```
TextDetector + TextRecognizer > 端到端OCR

优势：
✅ 模块化：独立优化和替换
✅ 效率：检测一次，识别多处
✅ 精度：专注各自任务
✅ 灵活：支持不同应用场景
```

### 7.3 在RAGFlow中的角色

- **TextDetector**：定位PDF页面中的文本块（标题、段落、表格等）
- **TextRecognizer**：识别文本块的实际内容（支持中英文混合）
- **协同效果**：实现高质量的文档数字化，为知识库构建提供基础

---

**文档版本**: v1.0
**创建日期**: 2025-12-25
**相关文件**:
- [TextDetector源码](../../../../../deepdoc/vision/ocr.py#L423-L574)
- [TextRecognizer源码](../../../../../deepdoc/vision/ocr.py#L142-L420)
- [OCR协作源码](../../../../../deepdoc/vision/ocr.py#L577-L797)
