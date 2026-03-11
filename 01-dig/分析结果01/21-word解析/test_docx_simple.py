#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docx类快速测试脚本 - 简化版本

使用方法:
    python test_docx_simple.py /path/to/document.docx
"""

import sys
import os
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


def quick_test(file_path):
    """快速测试Docx解析"""
    print(f"{'='*60}")
    print(f"测试文件: {file_path}")
    print(f"{'='*60}")

    if not os.path.exists(file_path):
        print(f"文件不存在: {file_path}")
        return

    # 导入
    from rag.app.naive import Docx

    # 读取文件
    with open(file_path, 'rb') as f:
        binary = f.read()

    print(f"文件大小: {len(binary)} 字节\n")

    # 解析
    parser = Docx()
    sections, tables = parser(file_path, binary=binary)

    # 结果
    print(f"{'='*60}")
    print(f"解析结果:")
    print(f"  段落数: {len(sections)}")
    print(f"  表格数: {len(tables)}")
    print(f"{'='*60}\n")

    # 段落预览
    print("前5个段落预览:")
    for i, (text, image) in enumerate(sections[:5]):
        has_img = "有图片" if image else "无图片"
        preview = text[:50].replace('\n', ' ')
        print(f"  [{i+1}] [{has_img}] {preview}...")

    # 表格预览
    if tables:
        print(f"\n表格预览 (共{len(tables)}个):")
        for i, table in enumerate(tables):
            html = table[0][1]
            rows = html.count('<tr>')
            caption = ""
            if '<caption>' in html:
                import re
                m = re.search(r'<caption>(.*?)</caption>', html)
                if m:
                    caption = f" - {m.group(1)}"
            print(f"  [{i+1}] {rows}行{caption}")

    return sections, tables


if __name__ == "__main__":

    file_path = "/Users/zhaob/tmp/02-kxtx/04-dev-data/03-test.docx"
    quick_test(file_path)
