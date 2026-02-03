    #
#  Copyright 2024 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

import logging
import math
import json
import re
import os
import numpy as np
from rag.nlp import rag_tokenizer
from common.file_utils import get_project_base_directory


class Dealer:
    def __init__(self):
        self.stop_words = set(["请问",
                               "您",
                               "你",
                               "我",
                               "他",
                               "是",
                               "的",
                               "就",
                               "有",
                               "于",
                               "及",
                               "即",
                               "在",
                               "为",
                               "最",
                               "有",
                               "从",
                               "以",
                               "了",
                               "将",
                               "与",
                               "吗",
                               "吧",
                               "中",
                               "#",
                               "什么",
                               "怎么",
                               "哪个",
                               "哪些",
                               "啥",
                               "相关"])

        def load_dict(fnm):
            res = {}
            f = open(fnm, "r")
            while True:
                line = f.readline()
                if not line:
                    break
                arr = line.replace("\n", "").split("\t")
                if len(arr) < 2:
                    res[arr[0]] = 0
                else:
                    res[arr[0]] = int(arr[1])

            c = 0
            for _, v in res.items():
                c += v
            if c == 0:
                return set(res.keys())
            return res

        fnm = os.path.join(get_project_base_directory(), "rag/res")
        self.ne, self.df = {}, {}
        try:
            self.ne = json.load(open(os.path.join(fnm, "ner.json"), "r"))
        except Exception:
            logging.warning("Load ner.json FAIL!")
        try:
            self.df = load_dict(os.path.join(fnm, "term.freq"))
        except Exception:
            logging.warning("Load term.freq FAIL!")

    def pretoken(self, txt, num=False, stpwd=True):
        patt = [
            r"[~—\t @#%!<>,\.\?\":;'\{\}\[\]_=\(\)\|，。？》•●○↓《；‘’：“”【¥ 】…￥！、·（）×`&\\/「」\\]"
        ]
        rewt = [
        ]
        for p, r in rewt:
            txt = re.sub(p, r, txt)

        res = []
        for t in rag_tokenizer.tokenize(txt).split():
            tk = t
            if (stpwd and tk in self.stop_words) or (
                    re.match(r"[0-9]$", tk) and not num):
                continue
            for p in patt:
                if re.match(p, t):
                    tk = "#"
                    break
            #tk = re.sub(r"([\+\\-])", r"\\\1", tk)
            if tk != "#" and tk:
                res.append(tk)
        return res

    def token_merge(self, tks):
        def one_term(t): return len(t) == 1 or re.match(r"[0-9a-z]{1,2}$", t)

        res, i = [], 0
        while i < len(tks):
            j = i
            if i == 0 and one_term(tks[i]) and len(
                    tks) > 1 and (len(tks[i + 1]) > 1 and not re.match(r"[0-9a-zA-Z]", tks[i + 1])):  # 多 工位
                res.append(" ".join(tks[0:2]))
                i = 2
                continue

            while j < len(
                    tks) and tks[j] and tks[j] not in self.stop_words and one_term(tks[j]):
                j += 1
            if j - i > 1:
                if j - i < 5:
                    res.append(" ".join(tks[i:j]))
                    i = j
                else:
                    res.append(" ".join(tks[i:i + 2]))
                    i = i + 2
            else:
                if len(tks[i]) > 0:
                    res.append(tks[i])
                i += 1
        return [t for t in res if t]

    def ner(self, t):
        if not self.ne:
            return ""
        res = self.ne.get(t, "")
        if res:
            return res

    def split(self, txt):
        '''
        返回一个经过空白符清洗 + 规则合词后的词元列表tks        
        双普通字母词元相邻则合并，只要有一个是函数名 / 末尾非字母 / 无前置词元，就不合并
        
        :param self: Description
        :param txt: Description
        '''
        tks = []
        #将文本中1 个及以上的连续空格 / 制表符替换成单个空格，解决原始文本中空白符不统一的问题（比如"a b\tc"会变成"a b c"）
        for t in re.sub(r"[ \t]+", " ", txt).split():
            # 得到词元  例如 rag  flow 会被分割为  rag,flow
            if tks and re.match(r".*[a-zA-Z]$", tks[-1]) and \
               re.match(r".*[a-zA-Z]$", t) and tks and \
               self.ne.get(t, "") != "func" and self.ne.get(tks[-1], "") != "func":
                tks[-1] = tks[-1] + " " + t
            else:
                tks.append(t)
        return tks

    def weights(self, tks, preprocess=True):
        #数字模式
        num_pattern = re.compile(r"[0-9,.]{2,}$")
        #短词组模式ab,ba,cd
        short_letter_pattern = re.compile(r"[a-z]{1,2}$")
        #数字空格模式
        num_space_pattern = re.compile(r"[0-9. -]{2,}$")
        #长词模式 
        letter_pattern = re.compile(r"[a-z. -]+$")

        # 命名实体识别权重
        def ner(t):
            #数字序列权重为2
            if num_pattern.match(t):
                return 2
            #短字母序列（1-2个字母）权重为0.01（极低权重）    
            if short_letter_pattern.match(t):
                return 0.01
            # 未识别实体权重为1 
            if not self.ne or t not in self.ne:
                return 1
            # 特定实体类型（公司、地点、学校、股票等）权重为3，有毒词为2，函数名为人名权重为    
            m = {"toxic": 2, "func": 1, "corp": 3, "loca": 3, "sch": 3, "stock": 3,
                 "firstnm": 1}
            return m[self.ne[t]]

        # 词性标注权重
        def postag(t):
            t = rag_tokenizer.tag(t)
            #代词、连词、副词权重为0.3（低权重）
            if t in set(["r", "c", "d"]):
                return 0.3
                
            # 地名、机构名权重为3（高权重）
            if t in set(["ns", "nt"]):
                return 3
                
            # 名词权重为2
            if t in set(["n"]):
                return 2
                
            # 数字序列权重为2    
            if re.match(r"[0-9-]+", t):
                return 2
            return 1

        def freq(t):
            # 数字空格模式权重为3
            if num_space_pattern.match(t):
                return 3
            # 使用分词器获取词频，未找到时对字母序列返回300
            s = rag_tokenizer.freq(t)
            # 长词模式，权重300 
            if not s and letter_pattern.match(t):
                return 300
            if not s:
                s = 0

            # 对长词进行细粒度分词后计算最小子词频的1/6
            if not s and len(t) >= 4:
                s = [tt for tt in rag_tokenizer.fine_grained_tokenize(t).split() if len(tt) > 1]
                if len(s) > 1:
                    s = np.min([freq(tt) for tt in s]) / 6.
                else:
                    s = 0

            return max(s, 10)

        # 文档频率计算
        def df(t):
            # 数字空格模式权重为3
            if num_space_pattern.match(t):
                return 5
            # 文档频率 权重+3    
            if t in self.df:
                return self.df[t] + 3
            #长词模式 权重300    
            elif letter_pattern.match(t):
                return 300
            #未找到时对长词进行细粒度分词后计算最小子词文档频率的1/6    
            elif len(t) >= 4:
                s = [tt for tt in rag_tokenizer.fine_grained_tokenize(t).split() if len(tt) > 1]
                if len(s) > 1:
                    return max(3, np.min([df(tt) for tt in s]) / 6.)

            return 3

        #逆文档频率计算
        def idf(s, N): return math.log10(10 + ((N - s + 0.5) / (s + 0.5)))

        tw = []
        if not preprocess: #不需要分词合并预处理kk

            # 词频计算
            # 标准实现模式：计算该词元在文档中的词频，既词元出现次数/文档总词汇数量,然后进行idf平滑处理
            # 实际实现为 :
            # 1. 获取词元在词典中的词频+根据词性硬编码得到词频权重
            # 2. 使用idf对估算词频权重进行平滑处理，反映词的"普遍重要性， 硬编码词汇数量为10000000
            idf1 = np.array([idf(freq(t), 10000000) for t in tks])
            

            # 文档频率计算
            # 标准实现模式：计算整个文档包含目标词元t的文档数量，既目标词元出现文档数量/文档总数量
            # 实际实现为 :
            # 1. 根据目标词元的模式(数字-字符)硬编码文档频率权重，如果有文档频率文件，则使用文档频率文件
            # 2. 使用idf对估算文档频率权重进行平滑处理，反映目标词元在整个文档中的 "区分能力"， 硬编码文档数量为10000000
            idf2 = np.array([idf(df(t), 1000000000) for t in tks])

            # 计算双 IDF 混合
            # 权重配比: 0.3 × IDF₁ + 0.7 × IDF₂
            # 既 0.3*词频 + 0.7 * 文档频率
            # 更看重文档频率（区分能力），兼顾词频（普遍性
            # 举例：
            # "人工智能" → freq 高 (常见)，但出现在很多文档 → df 也高 → IDF 较低
            # "BERT 模型" → freq 低，出现在少数文档 → IDF 较高


            # NER 实体加权  * postag 词性加权
            # 最终权重 = (0.3 × IDF₁ + 0.7 × IDF₂) × NER权重 × 词性权重
            wts = (0.3 * idf1 + 0.7 * idf2) * \
                np.array([ner(t) * postag(t) for t in tks])

            wts = [s for s in wts]
            tw = list(zip(tks, wts))
        else:#需要分词合并预处理
            for tk in tks:
                tt = self.token_merge(self.pretoken(tk, True))
                idf1 = np.array([idf(freq(t), 10000000) for t in tt])
                idf2 = np.array([idf(df(t), 1000000000) for t in tt])
                wts = (0.3 * idf1 + 0.7 * idf2) * \
                    np.array([ner(t) * postag(t) for t in tt])
                wts = [s for s in wts]
                tw.extend(zip(tt, wts))

        # 最终归一化,将所有权重转换为概率分布，总和为 1
        S = np.sum([s for _, s in tw])
        return [(t, s / S) for t, s in tw]
