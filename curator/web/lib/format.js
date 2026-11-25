// Display names for the values the pipeline writes and the curator adds. No preact here, so the
// module also runs under node.

export const STEP_NAME = { preprocess: '预处理', locate: '定位', extract: '提取' };
export const STEP_STATUS = { done: '完成', running: '运行中', failed: '失败' };
export const BLOCK_STATUS = { ok: '完成', failed: '失败', stale: '已过期' };
export const ENTRY_STATUS = { ok: '已拆分', failed: '拆分失败', pending: '未拆分', skipped: '未展开（超出条数限制）', stale: '已过期' };
export const REACTION_STATUS = { ok: '已提取', failed: '提取失败', pending: '待提取', stale: '已过期',
  skipped: '未提取（超出条数限制）' };

export const KIND = {
  optimization: '条件优化', substrate_scope: '底物范围', mechanistic: '机理实验', application: '应用',
  substrate_prep: '底物制备', catalyst_prep: '催化剂制备', background: '背景', mechanism_proposal: '机理推测',
  characterization: '表征', other: '其他',
};
export const ROLE = {
  catalyst: '催化剂', ligand: '配体', reagent: '试剂', additive: '添加剂', base: '碱', solvent: '溶剂',
  temperature: '温度', time: '时间', atmosphere: '气氛', other: '其他',
  reactant: '反应物', intermediate: '中间体', product: '产物', byproduct: '副产物',
};
// Step 1: what one entry of a block prints, how a region is printed, what an SI section holds,
// and how a region relates to another (from this region to the target).
export const LAYOUT = {
  condition_table: '条件表', product_scope: '产物范围', reactant_table: '反应物表', equation: '单个反应式',
  prose: '文字叙述', other: '其他',
};
export const PRESENTATION = { vector_graphic: '矢量图', raster_image: '位图', text_table: '文字表格', prose: '正文段落', scanned: '扫描页' };
export const SI_KIND = {
  general_info: '一般信息', optimization: '条件优化', general_procedure: '通用步骤', reaction_procedures: '逐个反应的步骤',
  substrate_prep: '底物制备', catalyst_prep: '催化剂制备', application: '应用', mechanistic: '机理实验',
  characterization: '表征数据', crystallography: '晶体结构', spectra: '谱图', computation: '计算', references: '参考文献', other: '其他',
};
export const RELATION = {
  subset_of: '是它的子集', superset_of: '比它完整', same_as: '与它相同', overlaps: '与它部分重叠',
  details_in: '细节见', procedure_in: '实验步骤见', characterization_in: '表征数据见',
};
export const YIELD_TYPE = {
  isolated: '分离', analytical: '分析', conversion: '转化率', other: '其他',
  NMR: 'NMR', GC: 'GC', HPLC: 'HPLC', LC: 'LC',
};
export const DOC = { main: '正文', si: 'SI' };
export const SOURCE = { drawn: '图中画出', text: '仅文字', derived: '由通式推出' };
export const ACTION = { remove: '去掉', replace: '改为', add: '加入', use: '选用' };

// ------------------------------------------------------------------ the curator

export const REVIEW_STATUS = { unreviewed: '未审核', reviewed: '已审核', problem: '有问题', excluded: '排除' };
// Chip / dot tone of a review status (common.js ReviewChip, .dot.<tone>).
export const REVIEW_TONE = { unreviewed: null, reviewed: 'ok', problem: 'bad', excluded: 'muted' };
export const REV_ACTION = {
  import: '导入', reimport: '重新导入', accept_import: '采用流水线新版本', dismiss_import: '忽略流水线新版本',
  edit: '编辑', review: '审核', revert: '回退', copy: '复制', create: '新建', delete: '删除', restore: '恢复',
  meta: '文献信息',
};
export const FLAG = { inferred: '含推断', unresolved: '有未确定项', issues: '有问题', warned: '流水线警告',
  yield_unspecified: '未明确产率', conditions_unspecified: '未明确条件', reference_unresolved: '引用未解析',
  variables_missing: '变量信息缺失', evidence_conflict: '存在矛盾', condition_applicability: '条件适用性存疑',
  other_review: '其他待核对', auxiliary: '辅助制备' };
export const FLAG_TONE = { inferred: 'infer', unresolved: 'bad', issues: 'bad', warned: 'warn',
  yield_unspecified: 'warn', conditions_unspecified: 'warn', reference_unresolved: 'warn', variables_missing: 'warn',
  evidence_conflict: 'bad', condition_applicability: 'bad', other_review: 'warn', auxiliary: 'muted' };
// One import of one paper (imports view).
export const IMPORT_OUTCOME = { imported: '已导入', skipped: '跳过', refused: '拒绝' };
export const IMPORT_COUNT = {
  inserted: '新增', superseded: '替换的旧反应', superseded_touched: '其中有人工修改', superseded_created: '其中人工新建',
  failed_not_imported: '失败未导入', blocks: '块', validation_errors: '校验错误', validation_warnings: '校验警告',
  // imports made before a re-import replaced a paper's reactions
  unchanged: '不变', reimported: '重新导入', pending: '待采用', missing: '缺失',
};

export const name = (table, value) => (value == null ? '' : table[value] || value);
export const where = (at) => (at ? `${name(DOC, at.doc)} p${at.page}` : '');

// R000123: how a reaction is named everywhere (list rows also carry it as `rid`).
export const displayId = (id) => (id == null ? '' : `R${String(id).padStart(6, '0')}`);

// Which layer of the block set a value: "base" (the scheme itself) is the normal case and has no label.
export function origin(value) {
  if (!value || value === 'base' || value === 'stated') return null;
  const [kind, detail] = [value.split(':')[0], value.split(':').slice(1).join(':')];
  return {
    footnote: `脚注 ${detail}`, entry: '本条', variant: `条件套 ${detail}`, default: '默认', lookup: '查文献',
    curator: '人工', 'step not part of this protocol': '本条无此步',
  }[kind] || value;
}

// The same on a chip next to a value: a reaction has one protocol, so its key need not be repeated.
export const originShort = (value) => (value && value.startsWith('variant:') ? '条件套' : origin(value));

const two = (n) => String(n).padStart(2, '0');
const date = (iso) => {
  const d = new Date(iso);
  return !iso || Number.isNaN(d.getTime()) ? null : d;
};

// "10-05 17:14" in local time.
export function clock(iso) {
  const d = date(iso);
  return d ? `${two(d.getMonth() + 1)}-${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}` : '';
}

// "2026-10-05 17:14" in local time (history, imports: where the year matters).
export function stamp(iso) {
  const d = date(iso);
  return d ? `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}` : '';
}

export const seconds = (s) => (s == null ? '' : s < 90 ? `${Math.round(s)} 秒` : `${Math.round(s / 60)} 分钟`);
export const cx = (...names) => names.filter(Boolean).join(' ');

// A value of a diff or a form in a few words: long text is cut, structures are named by what they hold.
export function brief(value, max = 60) {
  const cut = (s) => (s.length > max ? `${s.slice(0, max - 1)}…` : s);
  if (value === null || value === undefined) return '空';
  if (value === true) return '是';
  if (value === false) return '否';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') return value === '' ? '空文字' : cut(value);
  if (Array.isArray(value)) {
    if (!value.length) return '空列表';
    if (value.every((v) => v === null || ['string', 'number', 'boolean'].includes(typeof v))) {
      return cut(`[${value.map((v) => (v === null ? '空' : String(v))).join(', ')}]`);
    }
    return `${value.length} 项`;
  }
  // The record's small objects, as a person would name them (an added outcome is not raw JSON).
  if (value.yield && typeof value.yield === 'object') {
    const y = value.yield;
    return cut(`产率 ${y.text ?? y.value ?? '—'}${y.type ? `（${name(YIELD_TYPE, y.type)}）` : ''}`);
  }
  if (Array.isArray(value.reactants) && Array.isArray(value.products)) return `第 ${value.step ?? '?'} 步`;
  if (typeof value.doc === 'string' && value.page != null && !value.text) return where(value);
  if ('name' in value && 'value' in value) return cut(`${value.name ?? ''} = ${value.value ?? ''}`);
  if (typeof value.type === 'string' && typeof value.text === 'string' && Object.keys(value).length <= 2) {
    return cut(`${value.type} ${value.text}`);
  }
  const label = value.label || value.text || value.key || value.title;
  return label ? cut(String(label)) : cut(JSON.stringify(value));
}

// ------------------------------------------------------------------ diff paths

// Chinese words for the keys of a record (and of the state around it), for diffs and messages.
export const PATH_WORD = {
  data: '数据', review_status: '审核状态', review_note: '审核备注', deleted: '删除标记',
  reaction_id: '流水线编号', label: '标签', kind: '类型', variant: '条件套', conditions_given: '给出了条件',
  results: '印出的结果', inferences: '推断', source: '来源', steps: '步骤', conditions: '条件',
  removed_conditions: '不用的条件', unresolved: '未确定项', other_outcomes: '其他结果', footnotes: '脚注',
  related: '相关段落', notes: '备注', issues: '问题',
  doc: '文档', page: '页', figure: '图表', section: '章节', caption: '图注', region_id: '区域', block_id: '块',
  entry_id: '条目', entry_bbox: '条目框', crop: '截图',
  step: '步骤号', description: '描述', reactants: '反应物', products: '产物',
  key: '键', role: '角色', text: '文字', amount: '用量', amount_origin: '用量来源', amount_stated_at: '用量出处',
  unknown: '未知', generic: '通式', isolated: '已分离', bbox: '框', variables: '变量', name: '名称', value: '值',
  origin: '来源层', basis: '依据', alternatives: '候选', stated_at: '出处', choice: '选择', inferred: '推断',
  undecided_with: '二选一', preparation: '事先制备', in_yield: '计入产率', from: '原料', items: '条件',
  structure: '结构', value_missing: '本条未给出', outcomes: '结果', yield: '产率', qualifier: '限定',
  type: '类型', type_origin: '类型来源', selectivity: '选择性', footnote_markers: '脚注标记',
  participant_key: '参与物', about: '关于', title: '标题', authors: '作者', journal: '期刊', year: '年份', doi: 'DOI',
  note: '备注',
};
const PARTICIPANT_LISTS = new Set(['reactants', 'products']);

function word(seg, parent) {
  if (seg === 'text' && PARTICIPANT_LISTS.has(parent)) return '名称';
  if (seg === 'source' && PARTICIPANT_LISTS.has(parent)) return '结构来源';
  return PATH_WORD[seg] || seg;
}

// What people call the participants and conditions of a record, by key: {ester: '1', zncl2: 'ZnCl2'}.
// Keys are the record's internal names; paths of diffs and messages read better with labels.
export function keyNames(data) {
  const out = {};
  const short = (s) => (s.length > 24 ? `${s.slice(0, 23)}…` : s);
  const add = (x) => {
    if (x && typeof x === 'object' && typeof x.key === 'string' && x.key && !(x.key in out)) {
      const shown = x.label || x.text;
      if (shown && shown !== x.key) out[x.key] = short(String(shown));
    }
  };
  const list = (x) => (Array.isArray(x) ? x : []);
  for (const st of list(data?.steps)) {
    for (const p of [...list(st?.reactants), ...list(st?.products)]) add(p);
    list(st?.conditions).forEach(add);
  }
  list(data?.conditions).forEach(add);
  list(data?.removed_conditions).forEach(add);
  return out;
}

// ['data', 'steps', 0, 'reactants', {key: '1a'}, 'amount'] → "步骤 1 › 反应物 1a › 用量"; with `names`
// (keyNames) a key-addressed item is named by its label instead of its key.
// The leading 'data' of a history diff is left out; a string (an already rendered path) is returned as is.
export function describePath(path, names = null) {
  if (typeof path === 'string') return path;
  const segs = [...(path || [])];
  if (segs[0] === 'data' && segs.length > 1) segs.shift();
  const parts = [];
  let list = null;      // the list key the next segment indexes into
  let container = null; // the list the current item belongs to (for 'text' / 'source')
  for (const seg of segs) {
    const isItem = (seg && typeof seg === 'object') || typeof seg === 'number';
    if (isItem && list != null) {
      const n = typeof seg === 'number' ? seg + 1 : names?.[seg.key] ?? seg.key;  // indexes 1-based, as people count
      parts[parts.length - 1] = `${word(list, container)} ${n}`;
      container = list;
      list = null;
      continue;
    }
    if (isItem) {
      parts.push(typeof seg === 'number' ? `第 ${seg + 1} 项` : String(names?.[seg.key] ?? seg.key));
      continue;
    }
    parts.push(word(seg, container));
    list = seg;
  }
  return parts.join(' › ') || '整条记录';
}
