"""Prompts for the VLM tasks (T-004).

Every prompt demands JSON only and forbids guessing; unknown entries must be
omitted or returned as an empty array / ``null``.
"""

_JSON_RULES = (
    "只输出一个合法 JSON 对象，不要 Markdown 代码块、注释或任何解释文字。"
    "看不清、不确定或图中不存在的内容不要猜测：对应数组返回 []，不确定的标量返回 null。"
)

OCR_PROMPT = (
    "你是考古器物图的文字识别助手。识别图中的器物序号、比例尺和其余印刷文字，"
    "给出每个元素在图像像素坐标中的外接框 bbox=[x0,y0,x1,y1]。\n"
    "严格按以下结构输出：\n"
    '{"seqs":[{"text":"1","bbox":[x0,y0,x1,y1],"conf":0.9}],'
    '"scales":[{"text":"0 8厘米","bbox":[x0,y0,x1,y1],"value":8,"unit":"厘米",'
    '"prefix_nos":["1","2"]}],'
    '"texts":[{"text":"盖顶面纹饰","bbox":[x0,y0,x1,y1]}]}\n'
    "说明：seqs 为器物序号（text 保留图中写法）；scales 的比例尺 value 转为数字、unit 用图中单位，"
    "prefix_nos 为该比例尺适用的器物序号，不确定时返回 []；texts 为除序号和比例尺外的所有文字。"
    "没有对应内容时返回空数组；识别不到任何文字时返回 "
    '{"seqs":[],"scales":[],"texts":[]}。\n'
    + _JSON_RULES
)

VISUAL_PROMPT = (
    "你是考古器物图的视觉分析助手。请完成：(1) 判断图像类型（单线图/多线图/单版图/多版图/弃用）；"
    "(2) 判断各器物视图之间的关系（正面/侧面/俯视/剖面等是否同一器物、是否存在多器物拼版）；"
    "(3) 给出建议的切分区域 bbox，保证同一器物的多个视图不拆开；"
    "(4) 校验比例尺是否存在、读数是否与文字一致，矛盾时在 issues 中说明而不擅自取舍。\n"
    "严格按以下结构输出：\n"
    '{"image_type":"single_line_artifact","views":[{"label":"正面","bbox":[x0,y0,x1,y1],'
    '"same_artifact":true}],"regions":[{"bbox":[x0,y0,x1,y1],"artifact_hint":"1"}],'
    '"scale_check":{"scale_present":true,"consistent":true,"note":null},'
    '"issues":[],"confidence":0.8}\n'
    "无法判断的字段返回 null，无法确认的列表返回 []。\n" + _JSON_RULES
)

GLYPH_PROMPT = (
    "图像是一个网格，每个格子内有一个印刷字符（来自考古线图的器物序号）。"
    "按从左到右、从上到下的顺序，逐个识别格子里的字符；不是数字或字母的返回 null。"
    "共 {count} 个格子。只输出 JSON：{{\"glyphs\":[...]}}，长度必须为 {count}。\n"
    + _JSON_RULES
)

QC_PROMPT = (
    "你是考古图文配对结果的质量检查助手。检查给定的切分、序号映射、比例尺与正文配对结果是否存在缺陷："
    "序号漏配/错配、bbox 越界或重叠异常、比例尺缺失或多配、视图被拆开、文字与器物不一致等。\n"
    "严格按以下结构输出：\n"
    '{"verdict":"pass","defects":[{"code":"missing_seq","severity":"major",'
    '"message":"器物序号 3 未配对正文","bbox":[x0,y0,x1,y1]}],"needs_review":false}\n'
    "verdict 只能是 pass / fail / needs_review；defects 为空表示未发现缺陷；"
    "无法定位缺陷时 bbox 返回 null。\n" + _JSON_RULES
)
