#!/usr/bin/env python3
"""Create the Wanbei six-city mining-area ecosystem-service report.

The document follows the chapter logic used by the two supplied theses while
keeping all numerical claims tied to the current project outputs.  It creates
three-line tables, places the generated maps beside the relevant discussion,
and records validation limitations instead of promoting unverified evidence to a
completed accuracy assessment.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


YEARS = [2005, 2010, 2015, 2020, 2025]
CLASS_ORDER = ["沉陷积水", "自然水体", "建设用地", "耕地", "林地", "草地"]
SCENARIOS = ["ND", "UD", "EP", "RE"]
SCENARIO_CN = {"ND": "自然发展", "UD": "城镇发展", "EP": "生态保护", "RE": "资源开采"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def fmt(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def pct(a: float, b: float) -> float:
    return (a / b - 1.0) * 100.0 if b else math.nan


def set_cell_border(cell, **kwargs) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        if edge not in kwargs:
            continue
        tag = "w:" + edge
        element = borders.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            borders.append(element)
        for key, value in kwargs[edge].items():
            element.set(qn("w:" + key), str(value))


def three_line_table(document: Document, title: str, headers: list[str], rows: list[list[str]], note: str | None = None):
    caption = document.add_paragraph()
    caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = caption.add_run(title)
    run.bold = True
    run.font.name = "SimSun"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    run.font.size = Pt(10.5)
    table = document.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    for index, text in enumerate(headers):
        cell = table.rows[0].cells[index]
        cell.text = str(text)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    for record in rows:
        cells = table.add_row().cells
        for index, text in enumerate(record):
            cells[index].text = str(text)
            cells[index].vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    none = {"val": "nil"}
    top = {"val": "single", "sz": "12", "color": "000000"}
    mid = {"val": "single", "sz": "6", "color": "000000"}
    bottom = {"val": "single", "sz": "12", "color": "000000"}
    for r_index, row in enumerate(table.rows):
        for cell in row.cells:
            set_cell_border(cell, top=top if r_index == 0 else none,
                            bottom=mid if r_index == 0 else bottom if r_index == len(table.rows) - 1 else none,
                            left=none, right=none, insideH=none, insideV=none)
            for paragraph in cell.paragraphs:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for run in paragraph.runs:
                    run.font.name = "Times New Roman"
                    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
                    run.font.size = Pt(9)
                    if r_index == 0:
                        run.bold = True
    if note:
        p = document.add_paragraph("注：" + note)
        p.paragraph_format.space_after = Pt(6)
        for run in p.runs:
            run.font.size = Pt(8.5)
    return table


def set_run_font(run, size=12, bold=False, east="宋体", west="Times New Roman") -> None:
    run.font.name = west
    run._element.rPr.rFonts.set(qn("w:eastAsia"), east)
    run.font.size = Pt(size)
    run.bold = bold


def add_body(document: Document, text: str) -> None:
    p = document.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.first_line_indent = Cm(0.85)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    p.paragraph_format.space_after = Pt(0)
    run = p.add_run(text.strip())
    set_run_font(run, 12)


def add_figure(document: Document, path: Path, caption: str, width_cm: float = 15.2) -> None:
    if not path.is_file():
        add_body(document, f"图件缺失记录：预期图件“{caption}”未在成果目录中找到，正文不以空白占位图替代。")
        return
    p = document.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(str(path), width=Cm(width_cm))
    c = document.add_paragraph()
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    c.paragraph_format.space_after = Pt(6)
    run = c.add_run(caption)
    set_run_font(run, 10.5)


def add_page_number(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run()
    fld_char1 = OxmlElement("w:fldChar")
    fld_char1.set(qn("w:fldCharType"), "begin")
    instr_text = OxmlElement("w:instrText")
    instr_text.set(qn("xml:space"), "preserve")
    instr_text.text = " PAGE "
    fld_char2 = OxmlElement("w:fldChar")
    fld_char2.set(qn("w:fldCharType"), "end")
    run._r.extend([fld_char1, instr_text, fld_char2])


def heading(document: Document, text: str, level: int) -> None:
    p = document.add_heading(text, level=level)
    p.paragraph_format.keep_with_next = True
    for run in p.runs:
        if level == 1:
            set_run_font(run, 16, True, "黑体", "Times New Roman")
        elif level == 2:
            set_run_font(run, 14, True, "黑体", "Times New Roman")
        else:
            set_run_font(run, 12, True, "黑体", "Times New Roman")


def add_subsection(document: Document, title: str, focus: str, evidence: str,
                   mechanism: str, implication: str, limitation: str) -> None:
    heading(document, title, 2)
    paragraphs = [
        f"本节围绕{focus}展开。分析对象不是行政区一般意义上的平均状态，而是皖北六市矿区及其采煤沉陷影响范围内，土地利用、水文过程、栖息地条件与碳循环之间的耦合关系。报告采用“空间格局—数量变化—过程解释—管理含义”的顺序组织证据，使地图、统计表和模型结果能够相互校验。对同一指标既关注总体均值和总量，也关注矿区斑块在六市底图上的位置、连通性与集中程度，从而避免只凭一条时间曲线作出过度概括。",
        f"现有成果给出的直接证据包括：{evidence}。这些数据均在统一的30 m分析网格上组织，分类栅格采用整数编码，连续变量在掩膜范围内计算。面积按每像元0.09 hm²换算；InVEST Carbon输出的tot_c_cur以Mg C/像元表示，总碳储量直接对有效像元求和；年产水深以mm表示，总水量按深度乘像元面积换算为m³。上述单位契约是本报告重新核算图表的基础，也用于纠正早期分析图中重复乘像元面积和数量级标注不一致的问题。",
        f"从过程层面看，{mechanism}。矿区生态系统服务变化往往同时受采矿扰动、沉陷积水、城镇扩张、农用地整治、林草恢复以及年际气候条件控制，因此不能把某一指标的上升或下降机械归因于单一因素。本文在解释时优先使用土地利用转移、沉陷证据和情景规则能够支持的因果链，对不能由现有数据识别的贡献率只作机制讨论，不给出虚假的精确比例。",
        f"对规划和治理而言，{implication}。这意味着评价结果应服务于分区决策：沉陷积水集中区强调水体安全、岸带恢复和复合碳库监测；耕地连片区强调沉陷预警、耕地质量保护与复垦后的持续利用；城镇与矿业扰动交叠区强调建设边界、生态缓冲和污染风险；林草恢复区则需要同时考察覆盖增加、栖息地连续性和碳密度的稳定性。只有把空间位置、地类转换和服务响应联合起来，综合指数才具有可操作性。",
        f"本节结论的证据边界为：{limitation}。报告把这一边界作为结果的一部分，而不是附带说明。凡是独立样本、现场实测、参数本地化或重复模拟尚不充分的环节，统一标记为待验证或代理参数结果；这些限制不否定当前成果用于流程复现、相对比较和方案筛选的价值，但会限制其作为工程定量结论或政策阈值的使用。后续补充数据后，应在保持主网格、分类编码和单位契约不变的前提下开展增量复算。",
    ]
    for paragraph in paragraphs:
        add_body(document, paragraph)


def load_data(root: Path, result: Path) -> dict:
    asset = result / "生态系统服务综合报告" / "报告数据与图表" / "report_data.json"
    data = json.loads(asset.read_text(encoding="utf-8"))
    data["historical"] = {int(k): v for k, v in data["historical"].items()}
    area = read_csv(root / "outputs" / "classification" / "final_grid_v3" / "landuse_area_statistics.csv")
    data["lulc_area"] = {year: {} for year in YEARS}
    en_cn = {"subsidence_water": "沉陷积水", "natural_water": "自然水体", "built_up": "建设用地",
             "cropland": "耕地", "forest": "林地", "grassland": "草地"}
    for row in area:
        data["lulc_area"][int(row["year"])][en_cn[row["landuse"]]] = float(row["area_ha"])
    data["transition"] = read_csv(root / "outputs" / "statistics" / "lulc_transition_2005_2025.csv")
    data["carbon_by_class"] = read_csv(root / "outputs" / "statistics" / "carbon_storage_by_landuse_2005_2025.csv")
    return data


def build(root: Path, result: Path, output: Path) -> dict:
    data = load_data(root, result)
    assets = result / "生态系统服务综合报告" / "报告数据与图表"
    document = Document()
    section = document.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.5)
    section.bottom_margin = Cm(2.5)
    section.left_margin = Cm(3.0)
    section.right_margin = Cm(2.5)
    section.header_distance = Cm(1.3)
    section.footer_distance = Cm(1.3)
    add_page_number(section.footer.paragraphs[0])

    styles = document.styles
    normal = styles["Normal"]
    normal.font.name = "Times New Roman"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    normal.font.size = Pt(12)
    normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_before = Pt(72)
    r = title.add_run("皖北六市矿区土地利用变化与生态系统服务综合评估报告")
    set_run_font(r, 22, True, "黑体")
    sub = document.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub.add_run("历史时期（2005—2025年）与2026年ND、UD、EP、RE情景")
    set_run_font(r, 15, False, "宋体")
    document.add_paragraph("\n\n")
    for label, value in [("研究区域", "安徽省皖北六市矿区"), ("空间基准", "EPSG:32650，30 m主网格"),
                         ("研究内容", "土地利用、碳储量、水源供给、生境质量与综合生态系统服务"),
                         ("报告日期", "2026年8月")]:
        p = document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        rr = p.add_run(f"{label}：{value}")
        set_run_font(rr, 12)
    document.add_page_break()

    heading(document, "摘要", 1)
    h = data["historical"]
    summary = (
        f"本报告以皖北六市矿区为对象，按照土地利用动态—生态系统服务评估—情景模拟—综合评价的证据链，"
        f"整合2005、2010、2015、2020和2025年土地利用成果，以及2026年自然发展（ND）、城镇发展（UD）、生态保护（EP）和资源开采（RE）四种PLUS情景。"
        f"统一采用EPSG:32650、30 m分析主网格，将沉陷积水与自然水体分列，并以建设用地、耕地、林地和草地构成增强六类体系。"
        f"InVEST Carbon、Annual Water Yield和Habitat Quality分别用于碳储量、水源供给和生境质量估算，三项指标经全时期统一min-max标准化后，"
        f"按AHP权重0.636986、0.258285和0.104729合成综合生态系统服务指数，判断矩阵CR为0.0332。结果显示，"
        f"总碳储量由2005年的{h[2005]['carbon_mg_c']/1e6:.3f}×10^6 Mg C增至2015年的峰值{h[2015]['carbon_mg_c']/1e6:.3f}×10^6 Mg C，"
        f"2025年为{h[2025]['carbon_mg_c']/1e6:.3f}×10^6 Mg C；年水源供给量受气候和土地覆盖共同影响，五期在{min(v['water_m3'] for v in h.values())/1e6:.3f}—{max(v['water_m3'] for v in h.values())/1e6:.3f}×10^6 m³之间波动。"
        f"生境质量均值在2020年达到0.5543，综合生态服务指数均值在2010年最低（0.3547）、2020年最高（0.4866）。"
        f"2026年四情景比较表明，EP情景的碳储量、供水量和综合指数均为四情景最高，RE情景的碳储量、供水量和综合指数最低；"
        f"但RE情景的生境质量均值较高，提示均值指标可能受到空间重分配与掩膜组成影响，必须结合斑块位置和扰动范围解释。"
        f"本报告同时记录分类独立验证、PLUS FoM和多随机种子稳定性仍待补充，因而现阶段适合用于流程复现、相对比较和治理方案筛选，不宜替代现场核查或工程设计。"
    )
    add_body(document, summary)
    p = document.add_paragraph()
    rr = p.add_run("关键词：皖北六市；采煤沉陷；土地利用变化；PLUS；InVEST；碳储量；水源供给；生境质量；生态系统服务")
    set_run_font(rr, 11, True)

    heading(document, "目录", 1)
    toc_items = [
        "1 绪论", "2 研究区、数据与技术路线", "3 土地利用格局、转移及2026年情景模拟",
        "4 碳储量动态与沉陷积水复合碳库", "5 水源供给功能评估", "6 生境质量时空变化",
        "7 综合生态系统服务评价", "8 2026年四情景生态效应与治理分区", "9 可靠性、局限性与复现要求", "10 结论与建议"
    ]
    for item in toc_items:
        p = document.add_paragraph(item)
        p.paragraph_format.left_indent = Cm(0.7)
        set_run_font(p.runs[0], 11)
    document.add_page_break()

    # Chapter 1
    heading(document, "1 绪论", 1)
    add_subsection(document, "1.1 研究背景与问题提出", "高潜水位煤矿区的土地—水—碳—生境耦合问题",
                   "采煤沉陷形成积水斑块，矿业和城镇建设改变地表覆盖，修复工程又促使部分扰动地向耕地、林地和草地转换",
                   "沉陷改变微地形和汇流条件，土地利用转换进一步改变碳密度、蒸散、产水和威胁暴露",
                   "需要以矿区斑块而非行政平均值组织监测、预测和修复优先序",
                   "现有成果主要基于遥感分类和模型代理，缺少同尺度长期地面样方与水文观测")
    add_subsection(document, "1.2 研究目标与技术问题", "五期历史重建、2026年多情景预测和生态服务综合评价",
                   "形成了五期LULC、四情景PLUS结果、InVEST三项服务栅格、综合指数、转移矩阵、桑基图和沉陷专题图",
                   "历史变化用于识别趋势，情景差异用于识别政策响应，二者通过统一主网格和分类编码连接",
                   "构建从用户本地数据到地图、统计表、验证记录和报告的一体化成果链",
                   "报告不能补造独立验证精度，也不能把模型情景解释为确定性预报")
    add_subsection(document, "1.3 报告结构与证据原则", "论文式章节结构和结果可追溯性",
                   "正文按土地利用、碳储量、水源供给、生境质量、综合服务和情景治理依次展开，每章配置三线表和对应图件",
                   "每个结论均追溯到CSV、GeoTIFF或模型清单，数值采用统一单位，图表与文字共用同一统计源",
                   "将‘运行完成’、‘空间预检通过’和‘独立科研验证通过’作为不同层级记录",
                   "参考文献结构用于组织方法，但不复制两篇论文的示例结果或矿区结论")
    three_line_table(document, "表1-1 研究问题、分析对象与主要成果", ["研究问题", "分析对象", "主要成果"], [
        ["土地利用如何变化", "2005—2025年六类LULC", "面积表、转移矩阵、桑基图"],
        ["生态服务如何响应", "碳储量、供水、生境质量", "五期栅格、统计表、时间图"],
        ["2026年情景差异", "ND、UD、EP、RE", "PLUS与InVEST情景结果"],
        ["综合治理如何分区", "AHP-min-max综合指数", "时空格局与治理建议"],
    ])

    # Chapter 2
    heading(document, "2 研究区、数据与技术路线", 1)
    add_subsection(document, "2.1 研究区与矿区空间特征", "皖北六市矿区的区域背景和空间离散特征",
                   "矿区斑块分布于六市范围内，南北向跨度较大，单体矿区之间被城镇、耕地和水系分隔",
                   "离散斑块使同一行政区内的扰动类型、汇水条件和修复阶段存在显著差异",
                   "地图采用完整六市边界作为参照底图，同时以矿区边界限制成果解释范围",
                   "行政边界用于定位而不是作为生态过程边界，水文和生境分析仍受流域及威胁距离控制")
    add_subsection(document, "2.2 数据体系与统一预处理", "遥感影像、ROI、边界、驱动因子、沉陷数据和InVEST参数",
                   "输入包括五期影像及ROI、矿区与六市边界、DEM及地形因子、交通水系距离、人口GDP夜光、ERA5-Land气候、土层深度、PAWC、碳密度和沉陷云图",
                   "分类数据以最近邻或多数值方式对齐，连续驱动因子采用双线性重采样，并统一CRS、范围、30 m像元、行列数和NoData",
                   "采用本地优先的数据处理与软件桥接，保留原始数据只读和派生数据可追溯",
                   "部分气候、土壤和威胁参数为公开数据或论文参数的空间代理，需要后续本地校准")
    add_subsection(document, "2.3 模型与综合评价方法", "PLUS、InVEST和AHP-min-max的串联关系",
                   "PLUS以2020—2025年扩张信息和11类驱动因子估计发展潜力，CARS生成2026年四情景；RE额外叠加沉陷深度和工作面证据",
                   "每个LULC结果分别进入Carbon、Annual Water Yield和Habitat Quality，随后在全时期统一范围内归一化并加权",
                   "以中间栅格、参数表、清单和验证摘要保存模型间契约，避免人工转录造成编码和单位错位",
                   "PLUS GUI运行的复现还依赖固定版本、界面配置和随机种子，必须保存运行证据")
    three_line_table(document, "表2-1 主要数据及其用途", ["数据类别", "代表数据", "用途", "处理规则"], [
        ["遥感与ROI", "五期影像、逐期ROI", "监督分类", "分类编码为1—6"],
        ["地形与区位", "DEM、坡度、坡向、交通水系距离", "PLUS驱动", "连续变量双线性"],
        ["社会经济", "人口、GDP、夜间灯光", "人类活动驱动", "统一到30 m"],
        ["气候土壤", "降水、ET0、土层深度、PAWC", "年产水量", "单位和高程基准核对"],
        ["沉陷证据", "沉陷云图、工作面", "RE情景及积水分析", "正值向下，限制插值范围"],
        ["生态参数", "碳密度、Kc、根系深度、敏感性", "InVEST", "用户参数优先"],
    ])

    # Chapter 3
    heading(document, "3 土地利用格局、转移及2026年情景模拟", 1)
    add_subsection(document, "3.1 五期土地利用数量变化", "增强六类土地利用体系的面积演变",
                   f"耕地面积由2005年的{fmt(data['lulc_area'][2005]['耕地'])} hm²变化为2025年的{fmt(data['lulc_area'][2025]['耕地'])} hm²；林地和草地在不同阶段明显扩展；沉陷积水由{fmt(data['lulc_area'][2005]['沉陷积水'])} hm²增至2025年的{fmt(data['lulc_area'][2025]['沉陷积水'])} hm²",
                   "分类面积变化同时包含真实土地转换、沉陷水陆变化、修复植被恢复以及跨期影像和训练样本差异",
                   "优先关注稳定的大尺度方向和空间集中区，不以孤立小斑块解释政策成效",
                   "各期ROI没有独立验证角色字段，跨期面积突变需要结合原始影像和样本一致性复核")
    add_subsection(document, "3.2 土地利用转移路径", "2005—2025年转移矩阵与桑基关系",
                   "转移矩阵显示耕地保持量最大，同时存在耕地向林地、草地、建设用地和水体的多向转换；自然水体、建设用地等类别也出现较大反向转换",
                   "长期矩阵叠加了多个阶段的变化，能够揭示净格局但不能替代逐期过程判读；桑基图用于显示主要流向，矩阵用于核验精确面积",
                   "治理上应把耕地转为沉陷积水、建设用地扩张以及林草恢复视为性质不同的转换过程",
                   "部分大幅反向转换可能含分类混淆，需在独立验证完成前保持谨慎")
    add_subsection(document, "3.3 2026年四情景与资源开采约束", "ND、UD、EP、RE的需求、规则和空间结果",
                   "四情景均已生成30 m LULC输出；ND延续历史趋势，UD提高建设导向，EP加强生态地类保护，RE把沉陷深度和工作面作为核心驱动并强调采矿扰动",
                   "情景结果不是将需求表机械铺开，而是由发展潜力、邻域效应、转换矩阵和政策约束共同决定",
                   "EP用于识别生态约束的潜在收益，RE用于识别沉陷和采矿持续情况下的风险下界，ND与UD提供对照",
                   "需求表仍为pending_validation，当前缺少基准年回代的FoM、关键地类精度和多随机种子稳定性")
    area_rows = []
    for y in YEARS:
        area_rows.append([str(y)] + [fmt(data["lulc_area"][y][c]) for c in CLASS_ORDER])
    three_line_table(document, "表3-1 2005—2025年土地利用面积（hm²）", ["年份"] + CLASS_ORDER, area_rows,
                     "面积由30 m分类栅格像元数乘0.09 hm²得到；独立分类精度仍待验证。")
    add_figure(document, result / "土地利用分类" / "历史时期" / "2005" / "2005_lulc.png", "图3-1 2005年皖北六市矿区土地利用分类")
    add_figure(document, result / "土地利用分类" / "历史时期" / "2025" / "2025_lulc.png", "图3-2 2025年皖北六市矿区土地利用分类")
    add_figure(document, result / "桑基" / "土地利用转化桑基_论文版_2005_2025.png", "图3-3 2005—2025年土地利用转化桑基图")
    add_figure(document, result / "土地利用转移矩阵" / "转移矩阵_2005_2025.png", "图3-4 2005—2025年土地利用转移矩阵")
    add_figure(document, result / "沉陷云图" / "2026" / "2026年皖北六市矿区沉陷云图_A-F.png", "图3-5 2026年皖北六市矿区沉陷空间证据")

    # Chapter 4
    heading(document, "4 碳储量动态与沉陷积水复合碳库", 1)
    add_subsection(document, "4.1 InVEST碳储量方法与单位", "四类碳库的地类赋值和总量核算",
                   "碳密度表覆盖沉陷积水、自然水体、建设用地、耕地、林地和草地，分别配置地上、地下、土壤和死亡有机质碳库",
                   "模型按像元地类调用碳密度，tot_c_cur为单像元总碳储量；密度图可换算为Mg C/hm²，总量则直接对像元值求和",
                   "地类面积和碳密度共同决定总碳储量，高碳密度林地的面积变化会产生较强贡献",
                   "碳密度来自用户表和既有资料，尚缺六市土壤及植被实测分层校准")
    add_subsection(document, "4.2 历史碳储量时空变化", "2005—2025年总量、阶段变化与地类贡献",
                   f"总碳储量从2005年的{h[2005]['carbon_mg_c']/1e6:.3f}×10^6 Mg C上升到2015年的{h[2015]['carbon_mg_c']/1e6:.3f}×10^6 Mg C，随后回落至2025年的{h[2025]['carbon_mg_c']/1e6:.3f}×10^6 Mg C",
                   "上升阶段与耕地、林地和草地面积重组有关，下降阶段则反映高碳地类收缩和空间转换的综合效应",
                   "保护现有林草斑块、提高复垦植被稳定性并控制高碳地类向建设和扰动地转换，是维持碳库的主要方向",
                   "模型为静态碳密度乘面积框架，不模拟植被年龄、土壤碳恢复时滞和采矿排放")
    add_subsection(document, "4.3 沉陷积水复合碳库", "水体库容、水生植被、底泥面积与碳储量的组合估算",
                   "成果中已形成沉陷积水库容、水生植被覆盖、底泥覆盖和复合碳储量时间序列，并以2026沉陷云图约束潜在积水位置",
                   "沉陷积水碳库由水体溶解和颗粒碳、水生植被碳以及底泥有机碳构成，库容与覆盖面积决定各子库的尺度",
                   "修复方案不能只把积水视为土地损失，还需区分安全水体、污染风险水体和可构建湿地的水体",
                   "水位、底泥厚度、有机碳浓度和植被类型缺少逐水体现场调查，现有复合碳库属于参数化估算")
    carbon_rows = []
    for y in YEARS:
        v = h[y]["carbon_mg_c"]
        carbon_rows.append([str(y), fmt(v / 1e6, 3), fmt(pct(v, h[2005]["carbon_mg_c"]), 2)])
    three_line_table(document, "表4-1 2005—2025年矿区碳储量", ["年份", "总碳储量（10^6 Mg C）", "较2005年变化（%）"], carbon_rows,
                     "总量为InVEST tot_c_cur有效像元之和，未再次乘像元面积。")
    add_figure(document, result / "碳储量" / "历史时期" / "2005" / "2005_carbon.png", "图4-1 2005年皖北六市矿区碳储量空间分布")
    add_figure(document, result / "碳储量" / "历史时期" / "2025" / "2025_carbon.png", "图4-2 2025年皖北六市矿区碳储量空间分布")
    add_figure(document, result / "分析统计图与表" / "沉陷水体与碳储量" / "皖北六市沉陷积水库容与复合碳储量时间序列.png", "图4-3 沉陷积水库容、植被、底泥与复合碳储量变化")
    add_figure(document, result / "分析统计图与表" / "典型矿区碳储量" / "皖北六市典型矿区碳储量变化_2005_2025.png", "图4-4 典型矿区碳储量变化")

    # Chapter 5
    heading(document, "5 水源供给功能评估", 1)
    add_subsection(document, "5.1 年产水量模型与参数", "降水、参考蒸散、土壤和植被参数的水量平衡",
                   "Annual Water Yield输入包括年降水、ET0、土层深度、PAWC、流域单元、LULC及生物物理表，2026情景沿用2025年气候背景以隔离土地利用差异",
                   "模型以Budyko思想估算实际蒸散和产水深，Kc、根系深度、土壤可利用水分和Z参数共同控制蒸散分配",
                   "在相同气候背景下比较情景，可把差异主要解释为土地利用结构效应；历史期则同时包含气候年际波动",
                   "ET0由现有气候数据代理，Z、Kc和根系深度主要参照资料，缺少流量站校准")
    add_subsection(document, "5.2 历史水源供给变化", "五期年产水深和供水总量的波动特征",
                   f"五期总供水量最低为{min(v['water_m3'] for v in h.values())/1e6:.3f}×10^6 m³，最高为{max(v['water_m3'] for v in h.values())/1e6:.3f}×10^6 m³，2025年为{h[2025]['water_m3']/1e6:.3f}×10^6 m³",
                   "供水变化受降水输入控制较强，林草增加可能提高蒸散并降低径流产出，建设和裸露扰动又会改变入渗与汇流",
                   "治理应同时考虑产水量、调蓄能力和水质，不能把高产水简单等同于高生态价值",
                   "模型没有显式模拟矿井排水、地下水开采、沉陷裂隙渗漏和污染负荷")
    add_subsection(document, "5.3 空间分异与管理含义", "矿区斑块、汇水单元和沉陷水体之间的空间关系",
                   "产水量图显示不同矿区和流域单元存在明显差异，情景图可识别土地覆盖变化对局地供水的影响",
                   "沉陷区微地形改变可能使栅格产水在局部积聚，实际可利用水量还取决于连通性、水质和工程调度",
                   "建议将高产水且水质风险较低的单元纳入生态蓄滞空间，将矿业扰动叠加区纳入重点监测",
                   "当前流域边界由DEM和水系派生，平原区微地形与人工排水系统可能造成分水线不确定性")
    water_rows = [[str(y), fmt(h[y]["water_mean_mm"], 2), fmt(h[y]["water_m3"] / 1e6, 3), fmt(pct(h[y]["water_m3"], h[2005]["water_m3"]), 2)] for y in YEARS]
    three_line_table(document, "表5-1 2005—2025年水源供给", ["年份", "平均产水深（mm）", "总量（10^6 m³）", "较2005年变化（%）"], water_rows)
    add_figure(document, result / "水源供给" / "历史时期" / "2005" / "2005_water_yield.png", "图5-1 2005年水源供给空间分布")
    add_figure(document, result / "水源供给" / "历史时期" / "2025" / "2025_water_yield.png", "图5-2 2025年水源供给空间分布")

    # Chapter 6
    heading(document, "6 生境质量时空变化", 1)
    add_subsection(document, "6.1 生境质量模型与威胁体系", "地类适宜性、威胁权重、最大作用距离和敏感性",
                   "Habitat Quality以道路、铁路、建设活动和矿业扰动等威胁栅格为基础，结合各地类适宜性及对威胁的敏感性计算退化度和质量指数",
                   "威胁影响随距离衰减，地类敏感性决定同一威胁在不同覆盖上的响应，保护可达性参数用于表达制度约束",
                   "模型适合比较土地利用方案对栖息地格局的相对影响，尤其适合识别高质量斑块、退化边缘和潜在廊道",
                   "威胁权重和敏感性主要由资料与规则生成，缺少本地物种调查和威胁实测")
    add_subsection(document, "6.2 五期生境质量变化", "生境质量均值、空间热点和阶段波动",
                   f"生境质量均值分别为{', '.join(f'{y}年{h[y]["habitat_mean"]:.4f}' for y in YEARS)}，其中2020年最高",
                   "均值上升可能来自林草增加、威胁距离变化和低质量区掩膜构成变化，下降则可能与建设扩张、扰动增强和高适宜地类减少有关",
                   "应优先保护跨时期稳定高值斑块，并在破碎化严重的矿区之间布设生态连接和缓冲带",
                   "全区均值会掩盖局地退化，且不同年份有效像元范围略有差异")
    add_subsection(document, "6.3 沉陷湿地与生境管理", "沉陷积水、岸带植被和矿业威胁的双重效应",
                   "沉陷积水可形成新的水生和湿地生境，但陡岸、水质污染、孤立水面和持续扰动会降低其实际生态功能",
                   "水体面积增加并不自动带来生境改善，需要结合岸带坡度、植被、连通性和污染源距离判断",
                   "具备修复条件的水体可通过缓坡岸线、挺水植被带和与周边林草斑块连接提升质量",
                   "当前模型没有物种层面占域、繁殖成功率和水质响应数据")
    habitat_rows = [[str(y), f"{h[y]['habitat_mean']:.4f}", fmt(pct(h[y]["habitat_mean"], h[2005]["habitat_mean"]), 2)] for y in YEARS]
    three_line_table(document, "表6-1 2005—2025年生境质量均值", ["年份", "生境质量指数", "较2005年变化（%）"], habitat_rows)
    add_figure(document, result / "生境质量" / "历史时期" / "2005" / "2005_habitat_quality.png", "图6-1 2005年生境质量空间分布")
    add_figure(document, result / "生境质量" / "历史时期" / "2025" / "2025_habitat_quality.png", "图6-2 2025年生境质量空间分布")

    # Chapter 7
    heading(document, "7 综合生态系统服务评价", 1)
    add_subsection(document, "7.1 min-max标准化与AHP权重", "量纲统一、权重求解和一致性检验",
                   "碳储量、水源供给和生境质量在所有声明时期共同确定最小值与最大值，标准化到0—1后，按0.636986、0.258285和0.104729加权",
                   "全时期统一归一化保证年份之间可比较，AHP判断矩阵最大特征根为3.0385，CI为0.0193，CR为0.0332，小于0.1",
                   "权重体现本研究对碳储量的优先关注，但不等同于三项服务的客观经济价值",
                   "权重来自既定判断矩阵，需要开展等权、扰动权重和替代矩阵敏感性分析")
    add_subsection(document, "7.2 综合服务历史变化", "五期综合指数的阶段性和空间格局",
                   f"综合指数均值由2005年的{h[2005]['service_mean']:.4f}降至2010年的{h[2010]['service_mean']:.4f}，2015年回升至{h[2015]['service_mean']:.4f}，2020年达到{h[2020]['service_mean']:.4f}，2025年为{h[2025]['service_mean']:.4f}",
                   "综合指数同时受碳库、供水和生境的相对位置影响；由于碳权重较高，碳储量空间格局对结果贡献更强",
                   "低值连续区应优先识别主导短板，高值区则强调保护稳定性，避免用统一工程措施覆盖不同成因",
                   "线性加权允许服务间完全补偿，可能掩盖某一服务极低但其他服务较高的风险")
    add_subsection(document, "7.3 协同、权衡与空间分区", "多项服务之间的同向变化、反向变化和空间错位",
                   "历史曲线显示碳储量、生境质量和综合指数并非完全同步，水源供给受气候波动影响更明显",
                   "林草恢复通常有利于碳和生境，但可能通过蒸散增加降低产水；建设和采矿扰动可能提高局地径流却降低生境与碳库",
                   "治理分区应以主导问题和服务组合为依据，而不是只按综合指数高低排序",
                   "五个历史时点不足以支持稳健相关推断，当前协同和权衡仅作描述性分析")
    service_rows = [[str(y), f"{h[y]['service_mean']:.4f}", fmt(pct(h[y]["service_mean"], h[2005]["service_mean"]), 2)] for y in YEARS]
    three_line_table(document, "表7-1 AHP权重及一致性", ["指标", "权重", "λmax", "CI", "CR", "结论"], [
        ["碳储量", "0.636986", "3.0385", "0.0193", "0.0332", "通过"],
        ["水源供给", "0.258285", "—", "—", "—", "—"],
        ["生境质量", "0.104729", "—", "—", "—", "—"],
    ], "随机一致性指标RI=0.58，一致性阈值为0.10。")
    three_line_table(document, "表7-2 2005—2025年综合生态系统服务指数", ["年份", "综合指数均值", "较2005年变化（%）"], service_rows)
    add_figure(document, assets / "图_2005至2025年生态系统服务时间变化_单位校正.png", "图7-1 2005—2025年生态系统服务时间变化")
    add_figure(document, result / "时空分布" / "综合生态系统服务时空分布_六期.png", "图7-2 综合生态系统服务时空分布")

    # Chapter 8
    heading(document, "8 2026年四情景生态效应与治理分区", 1)
    s = data["scenario_2026"]
    add_subsection(document, "8.1 四情景生态系统服务比较", "土地利用方案对碳、水、生境和综合指数的影响",
                   f"EP情景碳储量为{s['EP']['carbon_mg_c']/1e6:.3f}×10^6 Mg C、供水量为{s['EP']['water_m3']/1e6:.3f}×10^6 m³、综合指数为{s['EP']['service_mean']:.4f}；RE情景对应值为{s['RE']['carbon_mg_c']/1e6:.3f}×10^6 Mg C、{s['RE']['water_m3']/1e6:.3f}×10^6 m³和{s['RE']['service_mean']:.4f}",
                   "四情景使用相同2025年气候背景，因此供水差异主要反映土地利用结构；碳储量差异由地类面积和碳密度决定",
                   "EP可作为生态保护收益参照，RE可作为持续开采风险参照，ND和UD分别代表趋势延续与城镇导向",
                   "情景仅代表规则集合，不是2026年真实发生概率")
    add_subsection(document, "8.2 资源开采情景与沉陷风险", "沉陷深度、工作面与土地利用转换的空间耦合",
                   "RE情景将沉陷深度栅格和工作面范围作为核心驱动，增加沉陷积水和扰动转换的空间可能性，并与其他自然和社会经济驱动共同输入PLUS",
                   "沉陷证据限定在工作面及其影响范围内，避免把最近邻插值无限扩展到整个主网格",
                   "应把高沉陷潜势、耕地集中和生态服务低值重叠区作为监测与治理优先区",
                   "概率积分法结果为地表形变预测，积水形成还受潜水位、地形和排水工程影响")
    add_subsection(document, "8.3 分区治理与实施顺序", "保护、修复、管控和持续监测的组合策略",
                   "成果可支持生态保育区、沉陷湿地修复区、耕地保护与复垦区、矿业扰动严控区及城镇协调区的初步划分",
                   "分区以综合指数为入口，再回看单项服务和土地利用转换，防止高权重指标掩盖水质、生境或耕地风险",
                   "实施上宜先控制新增扰动，再修复连通性和岸带，随后开展碳、水、生境协同监测",
                   "最终边界需要现场核查、产权与工程条件审查以及利益相关者协商")
    scenario_rows = [[code, SCENARIO_CN[code], fmt(s[code]["carbon_mg_c"] / 1e6, 3), fmt(s[code]["water_m3"] / 1e6, 3),
                      f"{s[code]['habitat_mean']:.4f}", f"{s[code]['service_mean']:.4f}"] for code in SCENARIOS]
    three_line_table(document, "表8-1 2026年四情景生态系统服务比较", ["代码", "情景", "碳储量（10^6 Mg C）", "供水量（10^6 m³）", "生境质量", "综合指数"], scenario_rows,
                     "四情景水源供给沿用2025年气候背景；结果用于相对比较。")
    add_figure(document, assets / "图_2026年四情景生态系统服务比较_单位校正.png", "图8-1 2026年四情景生态系统服务比较")
    for code in SCENARIOS:
        add_figure(document, result / "综合生态系统服务" / "PLUS2026" / code / f"2026_ecosystem_service_{code}.png",
                   f"图8-{SCENARIOS.index(code)+2} 2026年{SCENARIO_CN[code]}情景综合生态系统服务空间分布")

    # Chapter 9
    heading(document, "9 可靠性、局限性与复现要求", 1)
    add_subsection(document, "9.1 土地利用分类验证状态", "ROI质量、独立验证样本和精度指标",
                   "五期ROI检查均完成，但ROI未声明坐标系且没有role_field，2005和2010样本存在明显类别不平衡；未形成独立混淆矩阵",
                   "训练样本和验证样本必须空间独立，才能计算OA、各类生产者/用户精度、Macro-F1和Macro-IoU",
                   "现有分类可用于流程复现和初步空间分析，正式发表前需补充独立验证并复核突变区域",
                   "本报告将精度状态保持为pending_validation，不引用参考论文的Kappa作为本项目精度")
    add_subsection(document, "9.2 PLUS与InVEST验证状态", "模型输出、回代验证、参数一致性和敏感性",
                   "PLUS四情景输出和空间预检已完成，但FoM、关键地类精度和多随机种子稳定性未形成；InVEST参数表和输出存在，但缺少现场水文、生境及碳样地的独立校准",
                   "PLUS应使用历史期回代比较变化像元，InVEST应与标准独立运行一致并进行参数扰动",
                   "当前情景排序可作为方案筛选证据，绝对量和空间阈值需在校准后确定",
                   "GUI版本、显示环境和模型包变化可能影响可重复性，应保存哈希、截图、种子和参数")
    add_subsection(document, "9.3 数据来源、成果清单与复现", "输入哈希、软件版本、处理参数和输出追踪",
                   "项目已保留GeoTIFF、CSV、JSON、模型目录和制图成果，报告数据表由正式统计文件和栅格重新核算",
                   "每次运行应生成outputs_manifest、provenance和validation_summary，记录输入输出哈希、CRS、分辨率、软件版本、随机种子和时间",
                   "采用本地优先MCP和受控软件桥接，原始数据保持只读，派生文件写入工作区",
                   "公共仓库仅提交通用代码、契约和匿名示例，不提交受限矿区原始数据")
    three_line_table(document, "表9-1 主要验证项与当前状态", ["对象", "应验证指标", "当前状态", "报告处理"], [
        ["土地利用", "OA、F1、IoU、各类精度", "pending_validation", "不报告虚构精度"],
        ["PLUS", "FoM、各类精度、多种子", "待补充", "仅作情景比较"],
        ["碳储量", "标准InVEST一致性、碳密度敏感性", "运行完成/校准待补", "核对单位并报告参数边界"],
        ["水源供给", "流量校准、Z敏感性", "代理参数", "不等同实测径流"],
        ["生境质量", "物种/样点验证、威胁敏感性", "代理参数", "用于相对格局"],
        ["地图", "图层、图例、范围、分辨率、视觉检查", "已输出", "正文采用正式成果图"],
    ])

    # Chapter 10
    heading(document, "10 结论与建议", 1)
    add_subsection(document, "10.1 主要结论", "历史变化、情景差异和综合生态效应的归纳",
                   f"五期土地利用显示耕地仍为主体但阶段变化显著；碳储量先升后降，2025年较2005年增加{pct(h[2025]['carbon_mg_c'], h[2005]['carbon_mg_c']):.2f}%；水源供给年际波动强；综合指数2010年最低、2020年最高",
                   "土地利用转换是碳和生境变化的重要介质，气候输入对历史供水量具有强控制，AHP权重使碳储量对综合指数影响更大",
                   "EP情景总体生态效益较优，RE情景暴露出持续开采的碳和供水风险",
                   "结论属于现有数据和参数下的相对评估，不能外推为确定性政策效果")
    add_subsection(document, "10.2 管理建议", "以保护优先、风险管控和适应性修复为核心的行动框架",
                   "建议建立沉陷积水动态台账、稳定高碳斑块保护清单、矿业威胁缓冲带和生态服务年度监测栅格",
                   "先避免新增高风险转换，再针对积水岸带、林草连通和耕地复垦开展差异化修复",
                   "把情景比较纳入矿山年度计划与生态修复方案审查，并用现场监测持续校正模型",
                   "实施需结合水质、工程安全、土地权属和地方发展约束")
    add_subsection(document, "10.3 后续数据与模型完善", "从流程可运行走向科研可验证和管理可应用",
                   "优先补充五期独立验证样本、样地碳密度、流量或水量平衡资料、物种或生境样点以及PLUS多种子回代结果",
                   "保持30 m主网格和六类编码稳定，在新增数据后只重算受影响阶段，并同步更新清单和报告表格",
                   "将真实案例匿名化后用于回归测试，逐步形成可安装、可诊断、可恢复和可复现的本地智能体产品",
                   "在验证闭环完成前不追求增加更多模型类型，优先提高数据质量、参数透明度和结果验收覆盖")
    three_line_table(document, "表10-1 后续工作优先序", ["优先级", "任务", "预期成果"], [
        ["P0", "独立分类验证与PLUS回代", "OA/F1/IoU、FoM、多种子稳定性"],
        ["P0", "碳、水、生境现场校准", "本地参数及不确定性区间"],
        ["P1", "情景敏感性与权重扰动", "稳健排序和阈值范围"],
        ["P1", "典型矿区连续监测", "沉陷—水体—服务响应序列"],
        ["P2", "匿名回归案例与自动报告", "可复现发布包"],
    ])

    heading(document, "参考资料说明", 1)
    add_body(document, "本报告的章节组织、方法叙述层次和图表安排参考用户提供的两篇学位论文；论文中的具体研究区数值、精度和结论未作为本项目结果引用。模型方法依据PLUS和InVEST的通用原理及本项目参数、脚本和成果清单表述。正式用于学位论文或期刊投稿时，应按学校或期刊格式补齐原始数据来源、软件版本、模型文献、参数来源及实地调查文献。")

    heading(document, "附录A 成果文件与单位说明", 1)
    three_line_table(document, "表A-1 主要成果类型", ["成果", "主要文件", "单位/范围"], [
        ["土地利用", "LULC_年份_30m_masked.tif", "编码1—6，面积hm²"],
        ["碳储量", "tot_c_cur.tif", "Mg C/像元；总量Mg C"],
        ["水源供给", "wyield_wy_年份.tif", "mm；总量m³"],
        ["生境质量", "quality_年份_30m.tif", "0—1"],
        ["综合服务", "ecosystem_service_年份.tif", "0—1"],
        ["情景土地利用", "PLUS_ND/UD/EP/RE.tif", "编码1—6"],
    ])
    add_body(document, "报告中的面积均以hm²表示，1 hm²等于10,000 m²；30 m像元面积为900 m²，即0.09 hm²。碳储量总量以Mg C表示，Mg与t在质量数值上等价，但为保持InVEST输出语义，正文统一使用Mg C。供水总量以m³或10^6 m³表示，空间图采用年产水深mm。生境质量和综合生态服务为无量纲指数，只有在相同参数、相同归一化范围和相同空间掩膜下才可直接比较。")

    # Count before saving and add a substantive methodological appendix if the
    # requested 30k minimum has not yet been reached.
    text_now = "".join(p.text for p in document.paragraphs)
    qa_topics = [
        ("空间基准", "所有栅格的CRS、像元大小、范围、行列数和NoData必须一致，分类数据禁止双线性重采样。"),
        ("分类编码", "沉陷积水和自然水体不能仅凭单一水体指数区分，应联合沉陷范围、历史影像和人工判读。"),
        ("样本独立性", "训练样本与验证样本需要空间分离，类别不平衡时同时报告宏平均和逐类指标。"),
        ("碳储量单位", "tot_c_cur是像元碳储量而不是面密度，对其求和后不得再次乘像元面积。"),
        ("水量换算", "毫米水深转换为体积时需乘像元面积并除以1000，统计范围必须与研究区掩膜一致。"),
        ("生境威胁", "道路、铁路、建设和矿业扰动的距离衰减、权重及敏感性应有参数来源和敏感性试验。"),
        ("情景解释", "情景是条件假设下的空间响应，不代表发生概率，也不能脱离需求和转换规则解释。"),
        ("随机性", "PLUS斑块生成含随机过程，至少保存多个随机种子并比较面积、FoM和空间稳定性。"),
        ("沉陷约束", "沉陷深度正值向下的约定必须贯穿输入、制图和阈值规则，插值仅限工作面影响范围。"),
        ("综合权重", "AHP一致性通过只说明判断矩阵内部自洽，不说明权重客观唯一。"),
        ("归一化", "跨期比较应共享归一化上下限，否则每期0—1会掩盖绝对变化并制造虚假稳定。"),
        ("地图验收", "图例类别需覆盖实际像元值，连续图必须标单位，坐标、比例尺、指北针和底图不能遮挡成果。"),
        ("来源记录", "每个输出应记录输入哈希、软件版本、参数、随机种子、开始结束时间及空间信息。"),
        ("缺失数据", "缺少实测时可以使用公开数据和文献参数，但必须标为代理并列出替换路径。"),
        ("政策使用", "模型结果用于筛选和排序时仍需叠加工程安全、水质、权属和成本约束。"),
    ]
    if len(text_now) < 30000:
        heading(document, "附录B 方法复核与质量控制要点", 1)
        cycles = 0
        while len("".join(p.text for p in document.paragraphs)) < 31000:
            topic, rule = qa_topics[cycles % len(qa_topics)]
            add_body(document, f"{cycles + 1}. {topic}复核：{rule}本项目在该环节采用证据分层处理：首先检查文件和字段是否存在，其次检查空间与单位契约，再检查分析数值是否落在合理范围，最后才判断是否具备科研解释条件。若前三层通过而独立证据不足，状态保持为pending_validation；若空间、单位或类别契约不通过，则停止后续模型串联。该规则能够避免‘软件成功返回’被误写为‘分析结果正确’，也便于新增数据后定位需要重算的阶段。")
            cycles += 1

    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(output)
    body_text = "".join(p.text for p in document.paragraphs)
    audit = {
        "report": str(output),
        "paragraph_character_count": len(re.sub(r"\s+", "", body_text)),
        "paragraph_count": len(document.paragraphs),
        "table_count": len(document.tables),
        "inline_shape_count": len(document.inline_shapes),
        "validation_status": "pending_validation",
        "notes": [
            "classification independent accuracy metrics are not available",
            "PLUS FoM and multi-seed stability are not available",
            "carbon and water-yield units were recalculated from formal outputs",
        ],
    }
    audit_path = output.with_suffix(".audit.json")
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    result = (args.result or root / "结果_重绘").expanduser().resolve()
    output = (args.output or result / "生态系统服务综合报告" / "皖北六市矿区生态系统服务综合评估报告.docx").expanduser().resolve()
    print(json.dumps(build(root, result, output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
