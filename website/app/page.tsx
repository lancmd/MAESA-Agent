/* oxlint-disable next/no-img-element -- GitHub Pages needs a repository-relative public asset URL. */
import {
  ArrowRight,
  BarChart3,
  CheckCircle2,
  ChevronRight,
  CloudRain,
  ExternalLink,
  FileCheck2,
  GitFork,
  Layers3,
  Leaf,
  Map,
  Mountain,
  Network,
  ScanSearch,
  ShieldCheck,
  Sparkles,
  Trees,
  Waves,
} from 'lucide-react';

const REPO_URL = 'https://github.com/lancmd/MAESA-Skill';

const modules = [
  { icon: ScanSearch, title: '土地利用分类', text: '用 ENVI 或 PyTorch 完成逐期 LULC、置信度与独立精度评价。', tag: 'ENVI / PyTorch' },
  { icon: Network, title: 'PLUS 情景预测', text: '组织 ND、UD、EP、RE 四类情景，并保留回代与稳定性证据。', tag: 'PLUS V1.4.2' },
  { icon: Layers3, title: '碳储量核算', text: '依据可追溯碳密度表输出碳库栅格、总量与变化统计。', tag: 'InVEST Carbon' },
  { icon: CloudRain, title: '水源供给', text: '将降水、ET0、土壤与流域参数编译为可校准的数据栈。', tag: 'Annual Water Yield' },
  { icon: Trees, title: '生境质量', text: '基于威胁因子和敏感性表评价生境退化与质量格局。', tag: 'Habitat Quality' },
  { icon: Map, title: '论文级成果', text: '输出地图、时空统计、转移矩阵、Sankey 和可归档运行清单。', tag: 'ArcGIS / Matplotlib' },
];

const steps = [
  { number: '01', title: '交付数据', text: '从空白项目模板填写影像、边界、ROI、驱动因子和模型参数。' },
  { number: '02', title: '编译与运行', text: '先做空间预检，再按启用模块生成受控工作流并在本机运行。' },
  { number: '03', title: '验证与归档', text: '保留输入哈希、软件版本、状态、图表与原生模型输出。' },
];

export default function Home() {
  return (
    <main>
      <section className="hero-shell">
        <nav className="site-nav" aria-label="主导航">
          <a className="brand" href="#top" aria-label="MAESA Skill 首页">
            <span className="brand-mark"><Mountain size={18} strokeWidth={2.3} /></span>
            <span>MAESA <em>Skill</em></span>
          </a>
          <div className="nav-links"><a href="#capabilities">能力</a><a href="#workflow">流程</a><a href="#local">本地优先</a></div>
          <a className="nav-github" href={REPO_URL} target="_blank" rel="noreferrer"><GitFork size={16} /> GitHub</a>
        </nav>

        <div className="hero" id="top">
          <div className="hero-copy">
            <p className="eyebrow"><Sparkles size={14} /> 全国矿区生态分析应用技能</p>
            <h1>让矿区生态分析<br /><span>从影像走向证据</span></h1>
            <p className="hero-intro">将多期土地利用分类、PLUS 情景预测、InVEST 生态服务评价和科研制图，组织成留在你电脑上的可追溯工作流。</p>
            <div className="hero-actions">
              <a className="button primary" href={REPO_URL} target="_blank" rel="noreferrer">查看项目 <ArrowRight size={17} /></a>
              <a className="button secondary" href="#start">快速开始 <ChevronRight size={17} /></a>
            </div>
            <div className="trust-row"><span><CheckCircle2 size={16} /> 本地数据不上传</span><span><CheckCircle2 size={16} /> 运行过程可追溯</span></div>
          </div>
          <div className="hero-visual" aria-label="矿区生态分析工作流示意">
            <img src="maesa-hero.png" alt="矿区生态分析从采矿地貌到生态修复景观的工作流示意" />
            <div className="visual-label top-label"><span /> 多源遥感与驱动因子</div>
            <div className="visual-label bottom-label"><Leaf size={15} /> 生态服务成果</div>
          </div>
        </div>
      </section>

      <section className="signal-band" aria-label="产品特征">
        <div><strong>Local-first</strong><span>数据、软件与结果留在本机</span></div>
        <div><strong>6 类 LULC</strong><span>统一分类语义与统计边界</span></div>
        <div><strong>4 类 PLUS 情景</strong><span>ND / UD / EP / RE 独立管理</span></div>
        <div><strong>Evidence-ready</strong><span>状态、参数、哈希和图表齐备</span></div>
      </section>

      <section className="content-section modules-section" id="capabilities">
        <div className="section-heading">
          <div><p className="section-kicker">能力地图</p><h2>一个技能，串联完整生态分析链</h2></div>
          <p>按项目启用模块。缺少独立样本、回代证据或校准数据时，系统会如实标记状态，而非把“已运行”写成“已验证”。</p>
        </div>
        <div className="module-grid">
          {modules.map(({ icon: Icon, title, text, tag }) => <article className="module-card" key={title}>
            <div className="module-icon"><Icon size={22} /></div><p className="module-tag">{tag}</p><h3>{title}</h3><p>{text}</p>
          </article>)}
        </div>
      </section>

      <section className="workflow-section" id="workflow">
        <div className="workflow-intro"><p className="section-kicker">从输入到交付</p><h2>把复杂模型变成<br />清楚、可复查的路径</h2><p>MAESA 不替代专业判断；它把重复性高、容易漏项的检查、编译、执行和成果归档固定下来。</p></div>
        <div className="steps">
          {steps.map((step, index) => <article className="step" key={step.number}>
            <span className="step-number">{step.number}</span><h3>{step.title}</h3><p>{step.text}</p>{index < steps.length - 1 && <span className="step-line" aria-hidden="true" />}
          </article>)}
        </div>
      </section>

      <section className="content-section local-section" id="local">
        <div className="local-panel">
          <div className="local-icon"><ShieldCheck size={28} /></div>
          <div><p className="section-kicker">可信赖的本地运行</p><h2>不把研究区数据交给一个黑箱</h2><p>商业软件、原始影像、模型包和计算结果保留在本机。MCP 只作为应用技能与 ENVI、PLUS、InVEST、ArcGIS Pro 等软件之间的受控接口。</p></div>
          <ul><li><FileCheck2 size={17} /> 输入、参数和输出清单</li><li><BarChart3 size={17} /> 分类、PLUS、InVEST 验证状态</li><li><Waves size={17} /> 连续栅格与分类栅格分开处理</li></ul>
        </div>
      </section>

      <section className="start-section" id="start">
        <div><p className="section-kicker">快速开始</p><h2>从一个空白项目开始</h2><p>下载技能，复制项目模板，填入自己矿区的绝对路径。先完成预检，再选择需要的模型链。</p></div>
        <div className="install-card"><span className="terminal-dot" /><code>npx skills add lancmd/MAESA-Skill -g</code><a href={REPO_URL} target="_blank" rel="noreferrer" aria-label="在 GitHub 打开 MAESA Skill"><ExternalLink size={19} /></a></div>
      </section>

      <footer>
        <a className="brand" href="#top"><span className="brand-mark"><Mountain size={18} /></span><span>MAESA <em>Skill</em></span></a>
        <p>Mining Area Ecological Space Analysis · 本地矿区生态分析应用技能</p>
        <a href={REPO_URL} target="_blank" rel="noreferrer">开源于 GitHub <ArrowRight size={15} /></a>
      </footer>
    </main>
  );
}
