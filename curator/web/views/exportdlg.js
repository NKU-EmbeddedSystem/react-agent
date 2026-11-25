// The batch export: what to export (the list's filter or the chosen reactions), as JSON Lines or a ZIP
// with one JSON per reaction (optionally with structure pictures), and whether excluded and deleted
// reactions go too. The count shown is asked from the list API with the same selection the export
// makes, so it matches the file.
import { html, useState } from '../lib/preact.js';
import { exportBatch, listReactions } from '../lib/api.js';
import { useLoad } from '../lib/hooks.js';
import { emit } from '../lib/bus.js';
import { cx } from '../lib/format.js';
import { Dialog } from '../components/common.js';
import { describeFilters, exportQuery } from './filters.js';

const FORMATS = [
  ['jsonl', 'JSON Lines', '一个 .jsonl 文件，每行一条反应'],
  ['zip', 'ZIP（每条一个 JSON）', '每条反应一个 JSON 文件，附清单；可带结构图'],
];

export function ExportDialog({ filter = null, ids = null, names = {}, onClose }) {
  const [format, setFormat] = useState('jsonl');
  const [images, setImages] = useState(false);
  const [withExcluded, setWithExcluded] = useState(false);
  const [withDeleted, setWithDeleted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const options = { include_excluded: withExcluded, include_deleted: withDeleted };
  const query = exportQuery(filter, ids, options);
  const count = useLoad(() => (query ? listReactions({ ...query, limit: 0 }).then((d) => d.total) : Promise.resolve(0)),
    [query]);
  const n = count.data;
  const scope = ids ? `选中的 ${ids.length} 条反应` : describeFilters(filter, names) || '全部反应';

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await exportBatch({ filter: ids ? null : filter, ids, format, images: format === 'zip' && images,
        ...options });
      emit('toast', { text: `已导出 ${res.count} 条反应：${res.filename}`, tone: 'ok' });
      onClose();
    } catch (e) {
      setBusy(false);
      setError(e.message || String(e));
    }
  };

  return html`
    <${Dialog} title="导出反应" width=${540} onClose=${() => { if (!busy) onClose(); }}
               footer=${html`
                 <span class="xd-count" aria-live="polite">
                   ${count.error ? html`<span class="bad-text">数不出条数</span>`
                     : n == null ? '正在计算…' : html`将导出 <b>${n}</b> 条反应`}
                 </span>
                 <button type="button" class="btn" onClick=${onClose} disabled=${busy}>取消</button>
                 <button type="button" class="btn primary" onClick=${run} disabled=${busy || !n}>
                   ${busy ? '正在导出…' : '导出'}</button>`}>
      <div class="xd">
        <div class="xd-row">
          <span class="xd-k">范围</span>
          <span class="xd-scope">${ids ? '' : html`<span class="muted">当前筛选：</span>`}${scope}</span>
        </div>
        <div class="xd-row">
          <span class="xd-k">格式</span>
          <div class="xd-formats" role="radiogroup" aria-label="格式">
            ${FORMATS.map(([value, label, hint]) => html`
              <label key=${value} class=${cx('xd-opt', format === value && 'on')}>
                <input type="radio" name="xd-format" value=${value} checked=${format === value}
                       onChange=${() => setFormat(value)} />
                <span><b>${label}</b><small>${hint}</small></span>
              </label>`)}
          </div>
        </div>
        <div class="xd-row">
          <span class="xd-k"></span>
          <label class=${cx('check', format !== 'zip' && 'is-off')} title=${format === 'zip' ? null : '只有 ZIP 能带图片'}>
            <input type="checkbox" checked=${format === 'zip' && images} disabled=${format !== 'zip'}
                   onChange=${(e) => setImages(e.currentTarget.checked)} />
            含结构图（按记录里的框从 PDF 渲染 PNG，200 dpi）
          </label>
        </div>
        <div class="xd-row">
          <span class="xd-k">包括</span>
          <div class="xd-checks">
            <label class="check">
              <input type="checkbox" checked=${withExcluded} onChange=${(e) => setWithExcluded(e.currentTarget.checked)} />
              审核为“排除”的反应
            </label>
            <label class="check">
              <input type="checkbox" checked=${withDeleted} onChange=${(e) => setWithDeleted(e.currentTarget.checked)} />
              已删除的反应
            </label>
            <small class="field-hint">默认两者都不导出。辅助制备也默认排除，可筛选“辅助制备”或指定条目导出。</small>
          </div>
        </div>
        ${error ? html`<p class="form-error" role="alert">导出失败：${error}</p>` : null}
      </div>
    <//>`;
}
