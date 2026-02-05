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
import json
import re
from collections import defaultdict

from rag.utils.doc_store_conn import MatchTextExpr
from rag.nlp import rag_tokenizer, term_weight, synonym


class FulltextQueryer:
    def __init__(self):
        self.tw = term_weight.Dealer()
        self.syn = synonym.Dealer()
        self.query_fields = [
            "title_tks^10",
            "title_sm_tks^5",
            "important_kwd^30",
            "important_tks^20",
            "question_tks^20",
            "content_ltks^2",
            "content_sm_ltks",
        ]

    @staticmethod
    def sub_special_char(line):
        return re.sub(r"([:\{\}/\[\]\-\*\"\(\)\|\+~\^])", r"\\\1", line).strip()

    @staticmethod
    def is_chinese(line):
        arr = re.split(r"[ \t]+", line)
        if len(arr) <= 3:
            return True
        e = 0
        for t in arr:
            if not re.match(r"[a-zA-Z]+$", t):
                e += 1
        return e * 1.0 / len(arr) >= 0.7

    @staticmethod
    def rmWWW(txt):
        patts = [
            (
                r"是*(怎么办|什么样的|哪家|一下|那家|请问|啥样|咋样了|什么时候|何时|何地|何人|是否|是不是|多少|哪里|怎么|哪儿|怎么样|如何|哪些|是啥|啥是|啊|吗|呢|吧|咋|什么|有没有|呀|谁|哪位|哪个)是*",
                "",
            ),
            (r"(^| )(what|who|how|which|where|why)('re|'s)? ", " "),
            (
                r"(^| )('s|'re|is|are|were|was|do|does|did|don't|doesn't|didn't|has|have|be|there|you|me|your|my|mine|just|please|may|i|should|would|wouldn't|will|won't|done|go|for|with|so|the|a|an|by|i'm|it's|he's|she's|they|they're|you're|as|by|on|in|at|up|out|down|of|to|or|and|if) ",
                " ")
        ]
        otxt = txt
        for r, p in patts:
            txt = re.sub(r, p, txt, flags=re.IGNORECASE)
        if not txt:
            txt = otxt
        return txt

    @staticmethod
    def add_space_between_eng_zh(txt):
        # (ENG/ENG+NUM) + ZH
        txt = re.sub(r'([A-Za-z]+[0-9]+)([\u4e00-\u9fa5]+)', r'\1 \2', txt)
        # ENG + ZH
        txt = re.sub(r'([A-Za-z])([\u4e00-\u9fa5]+)', r'\1 \2', txt)
        # ZH + (ENG/ENG+NUM)
        txt = re.sub(r'([\u4e00-\u9fa5]+)([A-Za-z]+[0-9]+)', r'\1 \2', txt)
        txt = re.sub(r'([\u4e00-\u9fa5]+)([A-Za-z])', r'\1 \2', txt)
        return txt

    def question(self, txt, tbl="qa", min_match: float = 0.6):
        """
        问题分析与查询构建方法

        Args:
            txt: 原始问题文本
            tbl: 表格类型（默认qa）
            min_match: 最小匹配比例（默认0.6）

        Returns:
            MatchTextExpr: 匹配表达式
            keywords: 提取的关键词列表
        """
        original_query = txt
        
        #中英文混排处理,切分开中文英文
        txt = FulltextQueryer.add_space_between_eng_zh(txt)
        #规范化处理;全角转半角，繁体转简体;统一分隔符;转小写处理
        txt = re.sub(
            r"[ :|\r\n\t,，。？?/`!！&^%%()\[\]{}<>]+",
            " ",
            rag_tokenizer.tradi2simp(rag_tokenizer.strQ2B(txt.lower())),
        ).strip()
        otxt = txt

        # 停用词移除;去除疑问词；
        # 输入: "请问RAGFlow的检索流程是怎样的？"
        # 输出: "RAGFlow检索流程"
        txt = FulltextQueryer.rmWWW(txt)

        #英文处理流程
        if not self.is_chinese(txt):
            txt = FulltextQueryer.rmWWW(txt)
            tks = rag_tokenizer.tokenize(txt).split()
            keywords = [t for t in tks if t]
            tks_w = self.tw.weights(tks, preprocess=False)
            tks_w = [(re.sub(r"[ \\\"'^]", "", tk), w) for tk, w in tks_w]
            tks_w = [(re.sub(r"^[a-z0-9]$", "", tk), w) for tk, w in tks_w if tk]
            tks_w = [(re.sub(r"^[\+-]", "", tk), w) for tk, w in tks_w if tk]
            tks_w = [(tk.strip(), w) for tk, w in tks_w if tk.strip()]
            syns = []
            for tk, w in tks_w[:256]:
                syn = self.syn.lookup(tk)
                syn = rag_tokenizer.tokenize(" ".join(syn)).split()
                keywords.extend(syn)
                syn = ["\"{}\"^{:.4f}".format(s, w / 4.) for s in syn if s.strip()]
                syns.append(" ".join(syn))

            q = ["({}^{:.4f}".format(tk, w) + " {})".format(syn) for (tk, w), syn in zip(tks_w, syns) if
                 tk and not re.match(r"[.^+\(\)-]", tk)]
            for i in range(1, len(tks_w)):
                left, right = tks_w[i - 1][0].strip(), tks_w[i][0].strip()
                if not left or not right:
                    continue
                q.append(
                    '"%s %s"^%.4f'
                    % (
                        tks_w[i - 1][0],
                        tks_w[i][0],
                        max(tks_w[i - 1][1], tks_w[i][1]) * 2,
                    )
                )
            if not q:
                q.append(txt)
            query = " ".join(q)
            return MatchTextExpr(
                self.query_fields, query, 100, {"original_query": original_query}
            ), keywords

        def need_fine_grained_tokenize(tk):
            """
            判断是否需要对该 token 进行细粒度二次分词。
            
            规则：
            1. 长度小于 3 的 token 不再切分（太短无意义）。
            2. 仅由数字、小写字母及少量常用符号（.+#_*-）组成的 token 视为已足够原子，不再切分。
            3. 其余情况（如长中文串、混合大小写、含汉字等）返回 True，表示需要进一步切分。
            
            :param tk: 待判断的 token 字符串
            :return: True  -> 需要细粒度切分
                    False -> 保持原 token，不再切分
            """ 

            if len(tk) < 3:
                return False
            if re.match(r"[0-9a-z\.\+#_\*-]+$", tk):
                return False
            return True

        # 中文处理流程
        txt = FulltextQueryer.rmWWW(txt) #去除问题的无效疑问词

        qs, keywords = [], []

        # 术语分割-应该为最粗粒度的分割 根据空格给切出来
        # 合并相邻的英文词元,保留中文分隔,清理空白符
        #  "RAGFlow AI 人工智能" -> ["ragflow", "ai", "人工智能"]
        # txt = 程鹏是哪一年毕业的？毕业于什么院校？-> [程鹏是哪一年毕业的,毕业于院校]
        for tt in self.tw.split(txt)[:256]:  # .split():
            
            # tt = 程鹏是哪一年毕业的
            # tt = 毕业于院校
            # tt为术语,最粗粒度的拆分

            if not tt:
                continue
            
            # 分割完成的粗粒度术语，添加到关键词中
            keywords.append(tt)
            
            # 2. 对于术语进行分词并进行权重计算,通过文档频率，词频等计算 当前关键词的权重
            # 粗粒度关键词集合计算：最终权重 = (0.3 × IDF₁ + 0.7 × IDF₂) × NER权重 × 词性权重
            # 得到twts=复合词集合(带权重)
            twts = self.tw.weights([tt])
            
            # 查找术语的同义词，找到术语同义词，一并加入到关键词结果集合中
            syns = self.syn.lookup(tt)
            if syns and len(keywords) < 32:
                keywords.extend(syns)
            logging.debug(json.dumps(twts, ensure_ascii=False))


            tms = []

            # 按照权重降序遍历 复合词twts  枚举每个复合词tk 与 其权重w
            for tk, w in sorted(twts, key=lambda x: x[1] * -1):

                # 将复合关词tk 拆分 为更小的语义单元sm,例如："人工智能" → "人工 智能"
                # 细粒度分词会使用dfs枚举分词方案，并且对各个分词方案进行评分
                # 评分标准 奖励 少切，长词，既 切分的细一点，但是不要太碎
                sm = (
                    rag_tokenizer.fine_grained_tokenize(tk).split()
                    if need_fine_grained_tokenize(tk)
                    else []
                )
                sm = [
                    re.sub(
                        r"[ ,\./;'\[\]\\`~!@#$%\^&\*\(\)=\+_<>\?:\"\{\}\|，。；‘’【】、！￥……（）——《》？：“”-]+",
                        "",
                        m,
                    )
                    for m in sm
                ]

                #sm为去除特殊符号的 细粒度关键词集合
                sm = [FulltextQueryer.sub_special_char(m) for m in sm if len(m) > 1]
                sm = [m for m in sm if len(m) > 1]

                # 关键词结果集合 keywords 如果数量还不够32，那么加入复合词，和复合词的细粒度关键词
                if len(keywords) < 32:
                    keywords.append(re.sub(r"[ \\\"']+", "", tk))
                    keywords.extend(sm)

                # 寻找复合词的同义词,并加入关键词
                tk_syns = self.syn.lookup(tk)
                tk_syns = [FulltextQueryer.sub_special_char(s) for s in tk_syns]
                if len(keywords) < 32:
                    keywords.extend([s for s in tk_syns if s])

                # 对复合词的同义词，再进行细粒度分词，获取得分次高的分词方案
                tk_syns = [rag_tokenizer.fine_grained_tokenize(s) for s in tk_syns if s]
                tk_syns = [f"\"{s}\"" if s.find(" ") > 0 else s for s in tk_syns]

                if len(keywords) >= 32:
                    break



                # 步骤 6: 构建词元查询 (query.py:198-215)
                # 处理原词
                tk = FulltextQueryer.sub_special_char(tk)

                # 添加原词,如果原词中有多个词元，用""包裹
                if tk.find(" ") > 0:
                    tk = '"%s"' % tk
                    
                # 添加复合词的同义词的细粒度分词 (低权重 0.2),此时tk_syns为复合词的同义词的细粒度分词
                if tk_syns:
                    tk = f"({tk} OR (%s)^0.2)" % " ".join(tk_syns)
                    
                # 添加复合词的细粒度分词 (低权重 0.5, 近似匹配 ~2)
                if sm:
                    tk = f'{tk} OR "%s" OR ("%s"~2)^0.5' % (" ".join(sm), " ".join(sm))

                # 添加复合词和其权重 (查询表达式, 权重)
                if tk.strip():
                    tms.append((tk, w))

                #此时，原词术语tt，复合词，复合词的同义词的细粒度分词，复合词的细粒度分词 都已经考虑到

           
                '''
                Lucene 查询语法:

                tk = "人工智能"
                sm = ["人工", "智能"]
                tk_syns = ["机器智能"]

                构建:
                "人工智能"                    # 精确匹配
                OR ("机器智能")^0.2           # 同义词，权重 0.2
                OR "人工 智能"                # 细粒度分词（短语）
                OR ("人工 智能")~2^0.5        # 近似匹配，间隔2词内

                最终:
                "人工智能" OR ("机器智能")^0.2 OR "人工 智能" OR ("人工 智能")~2^0.5
                
                '''



            #步骤 7: 组合词元查询
            # 按权重组合所有词元
            tms = " ".join([f"({t})^{w}" for t, w in tms])

            # 如果有多个复合词，添加原术语的近似匹配
            if len(twts) > 1:
                tms += ' ("%s"~2)^1.5' % rag_tokenizer.tokenize(tt)

            # 构建术语级同义词查询
            syns = " OR ".join(
                [
                    '"%s"'
                    % rag_tokenizer.tokenize(FulltextQueryer.sub_special_char(s))
                    for s in syns
                ]
            )
            
            # 组合: 术语查询 (高权重) OR 同义词 (低权重)
            if syns and tms:
                tms = f"({tms})^5 OR ({syns})^0.7"

            qs.append(tms)

        if qs:
            query = " OR ".join([f"({t})" for t in qs if t])
            if not query:
                query = otxt


            # query = '((毕业)^0.5735432571633446 ("程 鹏")^0.3280436483358887 (哪一年 OR "一年" OR ("一年"~2)^0.5)^0.09841309450076662 ("程 鹏 是 哪一年 毕业 的"~2)^1.5) OR ((毕业)^0.5 (院校)^0.5 ("毕业 于 院校"~2)^1.5)'
    
            return MatchTextExpr(
                self.query_fields, query, 100, {"minimum_should_match": min_match, "original_query": original_query}
            ), keywords
            
        return None, keywords

    def hybrid_similarity(self, avec, bvecs, atks, btkss, tkweight=0.3, vtweight=0.7):
        from sklearn.metrics.pairwise import cosine_similarity
        import numpy as np

        sims = cosine_similarity([avec], bvecs)
        tksim = self.token_similarity(atks, btkss)
        if np.sum(sims[0]) == 0:
            return np.array(tksim), tksim, sims[0]
        return np.array(sims[0]) * vtweight + np.array(tksim) * tkweight, tksim, sims[0]

    def token_similarity(self, atks, btkss):
        def to_dict(tks):
            if isinstance(tks, str):
                tks = tks.split()
            d = defaultdict(int)
            wts = self.tw.weights(tks, preprocess=False)
            for i, (t, c) in enumerate(wts):
                d[t] += c
            return d

        atks = to_dict(atks)
        btkss = [to_dict(tks) for tks in btkss]
        return [self.similarity(atks, btks) for btks in btkss]

    def similarity(self, qtwt, dtwt):
        if isinstance(dtwt, type("")):
            dtwt = {t: w for t, w in self.tw.weights(self.tw.split(dtwt), preprocess=False)}
        if isinstance(qtwt, type("")):
            qtwt = {t: w for t, w in self.tw.weights(self.tw.split(qtwt), preprocess=False)}
        s = 1e-9
        for k, v in qtwt.items():
            if k in dtwt:
                s += v #* dtwt[k]
        q = 1e-9
        for k, v in qtwt.items():
            q += v #* v
        return s/q #math.sqrt(3. * (s / q / math.log10( len(dtwt.keys()) + 512 )))

    def paragraph(self, content_tks: str, keywords: list = [], keywords_topn=30):
        if isinstance(content_tks, str):
            content_tks = [c.strip() for c in content_tks.strip() if c.strip()]
        tks_w = self.tw.weights(content_tks, preprocess=False)

        origin_keywords = keywords.copy()
        keywords = [f'"{k.strip()}"' for k in keywords]
        for tk, w in sorted(tks_w, key=lambda x: x[1] * -1)[:keywords_topn]:
            tk_syns = self.syn.lookup(tk)
            tk_syns = [FulltextQueryer.sub_special_char(s) for s in tk_syns]
            tk_syns = [rag_tokenizer.fine_grained_tokenize(s) for s in tk_syns if s]
            tk_syns = [f"\"{s}\"" if s.find(" ") > 0 else s for s in tk_syns]
            tk = FulltextQueryer.sub_special_char(tk)
            if tk.find(" ") > 0:
                tk = '"%s"' % tk
            if tk_syns:
                tk = f"({tk} OR (%s)^0.2)" % " ".join(tk_syns)
            if tk:
                keywords.append(f"{tk}^{w}")

        return MatchTextExpr(self.query_fields, " ".join(keywords), 100,
                             {"minimum_should_match": min(3, len(keywords) / 10), "original_query": " ".join(origin_keywords)})
