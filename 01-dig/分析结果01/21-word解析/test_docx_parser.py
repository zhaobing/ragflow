#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docx类__call__()方法测试脚本

使用方法:
    python test_docx_parser.py /path/to/your/document.docx

输出:
    - 解析的段落列表(文本+图片信息)
    - 解析的表格列表(HTML格式)
    - 统计信息
"""

import sys
import os
from io import BytesIO
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# 导入必要的模块
try:
    from rag.app.naive import Docx
    from rag.nlp import concat_img
    from PIL import Image
    import re
except ImportError as e:
    print(f"导入错误: {e}")
    print("请确保在正确的环境中运行此脚本")
    sys.exit(1)


def print_separator(title=""):
    """打印分隔线"""
    if title:
        print(f"\n{'='*60} {title} {'='*60}")
    else:
        print(f"{'='*120}")


def print_paragraph_info(index, text, image, style):
    """打印段落信息"""
    print(f"\n[段落 {index+1}]")
    print(f"  样式: {style}")
    print(f"  文本长度: {len(text)} 字符")
    print(f"  文本内容: {text[:100]}{'...' if len(text) > 100 else ''}")

    if image:
        print(f"  图片: 有 (尺寸: {image.size[0]}x{image.size[1]})")
    else:
        print(f"  图片: 无")


def print_table_info(index, table_data):
    """打印表格信息"""
    image, html, position = table_data[0][0], table_data[0][1], table_data[1]

    print(f"\n[表格 {index+1}]")
    print(f"  图片: {'有' if image else '无'}")
    print(f"  HTML长度: {len(html)} 字符")

    # 提取表格标题
    caption_match = re.search(r'<caption>(.*?)</caption>', html)
    if caption_match:
        print(f"  标题: {caption_match.group(1)}")

    # 提取表格行数
    rows = re.findall(r'<tr>', html)
    print(f"  行数: {len(rows)}")

    # 显示HTML片段
    print(f"  HTML片段:\n{html[:200]}{'...' if len(html) > 200 else ''}")


def save_images_if_exists(sections, output_dir="./test_output"):
    """保存解析出的图片"""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    saved_count = 0
    for idx, (text, image) in enumerate(sections):
        if image:
            try:
                img_path = os.path.join(output_dir, f"paragraph_{idx+1}.jpg")
                image.save(img_path)
                print(f"已保存图片: {img_path}")
                saved_count += 1
            except Exception as e:
                print(f"保存图片失败: {e}")

    return saved_count


def test_docx_parser(file_path, save_images=False, verbose=True):
    """
    测试Docx解析器

    Args:
        file_path: Word文档路径
        save_images: 是否保存解析出的图片
        verbose: 是否打印详细信息
    """

    print_separator("开始解析Word文档")
    print(f"文件路径: {file_path}")
    print(f"文件存在: {os.path.exists(file_path)}")

    if not os.path.exists(file_path):
        print(f"\n错误: 文件不存在 - {file_path}")
        return None, None

    # 读取文件
    try:
        with open(file_path, 'rb') as f:
            binary = f.read()
        print(f"文件大小: {len(binary)} 字节")
    except Exception as e:
        print(f"\n错误: 读取文件失败 - {e}")
        return None, None

    # 创建解析器实例
    docx_parser = Docx()

    # 调用__call__方法进行解析
    print_separator("调用Docx.__call__()方法")

    try:
        sections, tables = docx_parser(file_path, binary=binary)
    except Exception as e:
        print(f"\n错误: 解析失败 - {e}")
        import traceback
        traceback.print_exc()
        return None, None

    # 打印解析结果
    print_separator("解析结果统计")
    print(f"段落数量: {len(sections)}")
    print(f"表格数量: {len(tables)}")

    # 统计图片数量
    image_count = sum(1 for _, img in sections if img is not None)
    print(f"包含图片的段落: {image_count}")

    # 统计样式分布
    style_count = {}
    for _, _, style in sections:
        style_count[style] = style_count.get(style, 0) + 1
    print(f"样式分布: {style_count}")

    if verbose:
        # 打印段落详情
        print_separator("段落详情")
        for idx, (text, image) in enumerate(sections):
            print_paragraph_info(idx, text, image, sections[idx][2] if len(sections[idx]) > 2 else "")

        # 打印表格详情
        if tables:
            print_separator("表格详情")
            for idx, table in enumerate(tables):
                print_table_info(idx, table)

        # 保存图片
        if save_images and image_count > 0:
            print_separator("保存图片")
            saved = save_images_if_exists(sections)
            print(f"共保存 {saved} 张图片")

    # 完整的HTML表格输出
    if tables and verbose:
        print_separator("完整HTML表格输出")
        for idx, table in enumerate(tables):
            print(f"\n--- 表格 {idx+1} HTML ---")
            print(table[0][1])

    print_separator("解析完成")
    return sections, tables


def test_with_sample_data():
    """使用示例数据进行测试"""
    print_separator("创建测试文档")

    # 这里可以创建一个简单的测试文档
    # 或者使用项目中已有的测试文档
    test_files = [
        # 添加测试文档路径
    ]

    # 如果没有指定测试文件，尝试从项目中查找
    project_test_files = list(Path(".").rglob("*.docx"))[:3]

    if project_test_files:
        print(f"找到 {len(project_test_files)} 个测试文档:")
        for f in project_test_files:
            print(f"  - {f}")

        print("\n使用第一个文档进行测试...")
        test_docx_parser(str(project_test_files[0]), save_images=True)
    else:
        print("未找到测试文档，请提供.docx文件路径")
        print("\n使用方法:")
        print("  python test_docx_parser.py /path/to/document.docx")
        print("  python test_docx_parser.py /path/to/document.docx --save-images")


class DocxParserTester:
    """Docx解析器测试类 - 提供更多测试方法"""

    def __init__(self, file_path):
        self.file_path = file_path
        self.sections = None
        self.tables = None
        self.docx_parser = Docx()

    def parse(self):
        """执行解析"""
        with open(self.file_path, 'rb') as f:
            self.binary = f.read()

        self.sections, self.tables = self.docx_parser(
            self.file_path,
            binary=self.binary
        )
        return self.sections, self.tables

    def get_sections_with_images(self):
        """获取包含图片的段落"""
        return [
            (idx, text, img)
            for idx, (text, img) in enumerate(self.sections)
            if img is not None
        ]

    def get_caption_sections(self):
        """获取Caption样式的段落"""
        return [
            (idx, text, img)
            for idx, (text, img, style) in enumerate(self.sections)
            if style == 'Caption'
        ]

    def get_tables_with_titles(self):
        """获取带标题的表格"""
        result = []
        for idx, table in enumerate(self.tables):
            html = table[0][1]
            caption_match = re.search(r'<caption>(.*?)</caption>', html)
            title = caption_match.group(1) if caption_match else ""
            if title:
                result.append((idx, title, html))
        return result

    def export_tables_to_markdown(self, output_file="./tables_export.md"):
        """将表格导出为Markdown格式"""
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("# Word表格导出\n\n")
            f.write(f"源文件: {self.file_path}\n\n")

            for idx, table in enumerate(self.tables):
                f.write(f"## 表格 {idx+1}\n\n")

                # 提取标题
                caption_match = re.search(r'<caption>(.*?)</caption>', table[0][1])
                if caption_match:
                    f.write(f"**标题**: {caption_match.group(1)}\n\n")

                # 简单的HTML转Markdown
                html = table[0][1]
                # 移除caption标签
                html = re.sub(r'<caption>.*?</caption>', '', html)
                # 转换table标签
                html = html.replace('<table>', '')
                html = html.replace('</table>', '')
                html = html.replace('<tr>', '| ')
                html = html.replace('</tr>', ' |')
                html = html.replace('<td>', '')
                html = html.replace('</td>', '')
                html = re.sub(r'<td colspan=\'\d+\'\s*>', '', html)

                f.write(html + "\n\n")

        print(f"表格已导出到: {output_file}")
        return output_file


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='Word文档解析测试工具')
    parser.add_argument('file_path', nargs='?', help='Word文档路径(.docx)')
    parser.add_argument('--save-images', action='store_true', help='保存解析出的图片')
    parser.add_argument('--export-tables', action='store_true', help='导出表格为Markdown')
    parser.add_argument('--output-dir', default='./test_output', help='输出目录')
    parser.add_argument('--quiet', action='store_true', help='静默模式(不打印详细信息)')

    args = parser.parse_args()

    if not args.file_path:
        # 没有提供文件路径时，尝试查找测试文档
        test_with_sample_data()
        return

    # 执行解析
    sections, tables = test_docx_parser(
        args.file_path,
        save_images=args.save_images,
        verbose=not args.quiet
    )

    if sections is None or tables is None:
        print("\n解析失败!")
        return 1

    # 导出表格
    if args.export_tables and tables:
        print_separator("导出表格")
        tester = DocxParserTester(args.file_path)
        tester.sections = sections
        tester.tables = tables
        tester.export_tables_to_markdown(
            os.path.join(args.output_dir, "tables_export.md")
        )

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
