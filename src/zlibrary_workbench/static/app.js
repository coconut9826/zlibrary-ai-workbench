const $ = (selector) => document.querySelector(selector);
const api = async (path, options = {}) => {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail?.message || payload.detail?.code || payload.error || `请求失败 (${response.status})`);
  return payload;
};
let toastTimer;
const toast = (message, error = false) => {
  const node = $('#toast'); node.textContent = message; node.className = `show${error ? ' error' : ''}`;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { node.className = ''; }, 4200);
};
const escaped = (value = '') => String(value).replace(/[&<>"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[char]));

async function loadBooks() {
  const query = $('#library-query').value.trim();
  const data = await api(`/v1/library?query=${encodeURIComponent(query)}`);
  const grid = $('#book-grid');
  grid.innerHTML = data.books.map((book) => `<article class="book-card"><h3>${escaped(book.title)}</h3><p>${escaped(book.author || '作者未知')} ${book.year ? `· ${escaped(book.year)}` : ''}</p><div class="chips">${(book.categories || []).map((item) => `<span class="chip">${escaped(item)}</span>`).join('')}${(book.files || []).map((file) => `<span class="chip">${escaped(file.format)}</span>`).join('')}</div><p>${(book.files || []).length} 个文件版本</p></article>`).join('');
  $('#books-empty').hidden = data.books.length > 0;
}
async function loadTasks() {
  const data = await api('/v1/jobs');
  $('#task-list').innerHTML = data.jobs.map((job) => `<article class="task"><strong>${escaped(job.kind)}</strong><p>${escaped(job.status)} · ${Math.round((job.progress || 0) * 100)}%</p><p>${escaped(job.id)}</p></article>`).join('');
  $('#tasks-empty').hidden = data.jobs.length > 0;
}
async function upload(file) {
  const body = new FormData(); body.append('file', file);
  const data = await api('/v1/files/upload', {method:'POST', body});
  return data.path;
}
async function loadSettings() {
  const data = await api('/v1/settings'); const config = data.config; const form = $('#settings-form');
  Object.entries({library_root:config.paths.library_root, downloads:config.paths.downloads, converted:config.paths.converted, audiobooks:config.paths.audiobooks, reports:config.paths.reports, naming_template:config.naming.template, collision:config.naming.collision, ollama_model:config.ollama.model, audiosmith_voice:config.audiosmith.voice, audiosmith_model:config.audiosmith.model}).forEach(([key,value]) => { form.elements[key].value = value || ''; });
}
function metadata(form) { return {title:form.elements.title.value.trim(), author:form.elements.author.value.trim(), language:form.elements.language?.value.trim() || '', format:''}; }

document.querySelectorAll('.tab').forEach((button) => button.addEventListener('click', () => { document.querySelectorAll('.tab,.page').forEach((node) => node.classList.remove('active')); button.classList.add('active'); $(`#${button.dataset.page}`).classList.add('active'); }));
$('#library-query').addEventListener('input', () => loadBooks().catch((error) => toast(error.message,true)));
$('#refresh-tasks').addEventListener('click', () => loadTasks().catch((error) => toast(error.message,true)));
$('#search-form').addEventListener('submit', async (event) => { event.preventDefault(); const form = event.currentTarget; try { const data = await api('/v1/books/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(form)))}); $('#search-results').innerHTML = (data.books || []).map((book) => `<article class="result card"><div><strong>${escaped(book.title)}</strong><p>${escaped(book.author || '')} · ${escaped(book.year || '')} · ${escaped(book.extension || '')}</p></div><button data-book="${encodeURIComponent(JSON.stringify(book))}">确认下载</button></article>`).join('') || '<p class="empty">没有搜索结果。</p>'; document.querySelectorAll('[data-book]').forEach((button) => button.addEventListener('click', () => downloadBook(JSON.parse(decodeURIComponent(button.dataset.book)))); } catch(error) { toast(error.message,true); } });
async function downloadBook(book) { if (!confirm(`确认下载《${book.title}》？这可能消耗账号下载额度。`)) return; try { const data = await api('/v1/books/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:String(book.id),hash:String(book.hash),confirmed:true,metadata:{title:book.title,author:book.author || '',year:String(book.year || ''),language:book.language || '',format:book.extension || ''}})}); toast(`已加入书架：${data.library.path}`); loadBooks(); } catch(error) { toast(error.message,true); } }
$('#convert-form').addEventListener('submit', async (event) => { event.preventDefault(); const form = event.currentTarget; try { const path = await upload(form.elements.file.files[0]); const data = await api('/v1/convert/pdf-to-epub',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,metadata:metadata(form),mode:form.elements.mode.value})}); toast(`转换完成：${data.library.path}`); loadBooks(); } catch(error) { toast(error.message,true); } });
$('#summary-form').addEventListener('submit', async (event) => { event.preventDefault(); const form = event.currentTarget; try { const path = await upload(form.elements.file.files[0]); const data = await api('/v1/analysis/report',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,title:form.elements.title.value,author:form.elements.author.value})}); toast(`报告已生成：${data.markdown}`); loadBooks(); } catch(error) { toast(error.message,true); } });
$('#audio-form').addEventListener('submit', async (event) => { event.preventDefault(); const form = event.currentTarget; try { const path = await upload(form.elements.file.files[0]); const data = await api('/v1/audiosmith/audiobooks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,metadata:{title:form.elements.title.value,author:'',language:'',format:''},voice:form.elements.voice.value})}); toast(`有声书项目已创建：${data.project_id}`); loadTasks(); } catch(error) { toast(error.message,true); } });
$('#settings-form').addEventListener('submit', async (event) => { event.preventDefault(); try { const payload = Object.fromEntries(new FormData(event.currentTarget)); await api('/v1/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); toast('设置已保存。'); loadBooks(); } catch(error) { toast(error.message,true); } });
(async () => { try { const health = await api('/health'); $('#connection').textContent = `本机书库已连接 · ${health.library_root}`; await Promise.all([loadBooks(), loadTasks(), loadSettings()]); } catch(error) { $('#connection').textContent = '本地服务不可用'; toast(error.message,true); } })();
