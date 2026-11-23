const $ = (selector) => document.querySelector(selector);
const api = async (path, options = {}) => {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const validation = Array.isArray(payload.detail) ? payload.detail.map((item) => `${item.loc?.slice(-1)[0] || '参数'}：${item.msg}`).join('；') : '';
    throw new Error(validation || payload.detail?.message || payload.detail?.code || payload.error || `请求失败 (${response.status})`);
  }
  return payload;
};
let toastTimer;
let shelfBooks = [];
let searchSequence = 0;
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
  shelfBooks = data.books;
  populateLibrarySources();
}
async function loadTasks() {
  const data = await api('/v1/jobs');
  const labels = {download:'下载', audiobook_project:'有声书项目', audiobook_render:'有声书渲染'};
  const states = {running:'进行中', completed:'已完成', failed:'失败', prepared:'已准备', queued:'排队中'};
  $('#task-list').innerHTML = data.jobs.map((job) => `<article class="task"><strong>${escaped(labels[job.kind] || job.kind)} · ${escaped(job.payload.title || job.payload.project_id || job.id)}</strong><p>${escaped(states[job.status] || job.status)} · ${Math.round((job.progress || 0) * 100)}%</p>${job.error ? `<p class="task-error">${escaped(job.error)}</p>` : ''}</article>`).join('');
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
async function loadZLibraryStatus() {
  const data = await api('/v1/zlibrary/status');
  const form = $('#login-form');
  form.elements.account.value = data.account || 'default';
  form.elements.email.value = data.email || '';
  form.elements.remember_password.checked = Boolean(data.remember_password);
  const accounts = data.accounts.accounts || [];
  const picker = $('#account-picker');
  $('#account-picker-wrap').hidden = accounts.length === 0;
  picker.innerHTML = accounts.map((item) => `<option value="${escaped(item.name)}">${escaped(item.name)}${item.is_default ? '（当前）' : ''}${item.has_saved_password ? ' · 已记住密码' : ''}</option>`).join('');
  picker.value = data.account || data.accounts.default_account || '';
  const state = accounts.length ? `已保存会话：${accounts.map((item) => item.name).join('、')}` : '尚未登录本地账号';
  $('#zlibrary-status').textContent = `${state}${data.has_saved_password ? ' · 密码已存入钥匙串' : ''}`;
}
function metadata(form) { return {title:form.elements.title.value.trim(), author:form.elements.author.value.trim(), language:form.elements.language?.value.trim() || '', format:''}; }
function libraryOptions(accept) { const formats = accept.split(',').map((value) => value.trim().toLowerCase()); return shelfBooks.flatMap((book) => (book.files || []).filter((file) => formats.includes(String(file.format || '').toLowerCase())).map((file) => ({book, file}))); }
function populateLibrarySources() { document.querySelectorAll('.library-file').forEach((select) => { const selected = select.value; const items = libraryOptions(select.dataset.accept || ''); select.innerHTML = `<option value="">${items.length ? '请选择书架中的文件' : '书架中暂无兼容文件'}</option>` + items.map(({book, file}) => `<option value="${escaped(file.path)}" data-book="${escaped(String(book.id))}">${escaped(book.title)}${book.author ? ` · ${escaped(book.author)}` : ''} (${escaped(file.format)})</option>`).join(''); if (items.some(({file}) => file.path === selected)) select.value = selected; }); }
function syncSourceMode(form) { const library = form.elements.source.value === 'library'; form.querySelector('.library-source').hidden = !library; form.querySelector('.external-source').hidden = library; form.elements.file.required = !library; form.elements.library_file.required = library; }
function fillMetadataFromShelf(form) { const select = form.elements.library_file; const bookId = Number(select.options[select.selectedIndex]?.dataset.book); const book = shelfBooks.find((item) => item.id === bookId); if (!book) return; if (form.elements.title) form.elements.title.value = book.title || ''; if (form.elements.author) form.elements.author.value = book.author || ''; if (form.elements.language && book.language) form.elements.language.value = book.language; }
async function sourcePath(form) { if (form.elements.source.value === 'library') { const path = form.elements.library_file.value; if (!path) throw new Error('请从内置书架选择一个文件，或切换为从电脑导入。'); return path; } const file = form.elements.file.files[0]; if (!file) throw new Error('请选择要从电脑导入的文件。'); const formats = form.elements.library_file.dataset.accept.split(','); if (!formats.includes(file.name.split('.').pop().toLowerCase())) throw new Error('文件格式与当前功能不兼容。'); if (file.size > 512 * 1024 * 1024) throw new Error('文件不能超过 512 MiB。'); return upload(file); }

document.querySelectorAll('.tab').forEach((button) => button.addEventListener('click', () => { document.querySelectorAll('.tab,.page').forEach((node) => node.classList.remove('active')); button.classList.add('active'); $(`#${button.dataset.page}`).classList.add('active'); }));
document.querySelectorAll('.source-choice').forEach((select) => select.addEventListener('change', () => syncSourceMode(select.form)));
document.querySelectorAll('.library-file').forEach((select) => select.addEventListener('change', () => fillMetadataFromShelf(select.form)));
$('#library-query').addEventListener('input', () => loadBooks().catch((error) => toast(error.message,true)));
$('#refresh-tasks').addEventListener('click', () => loadTasks().catch((error) => toast(error.message,true)));
$('#login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = $('#login-submit');
  if (!form.reportValidity()) return;
  submit.disabled = true;
  submit.textContent = '正在通过 Tor 登录…';
  $('#zlibrary-status').textContent = '正在通过本机 Tor 建立登录会话，请稍候…';
  try {
    const payload = {
      email: form.elements.email.value.trim(),
      password: form.elements.password.value,
      account: form.elements.account.value.trim() || 'default',
      remember_password: form.elements.remember_password.checked,
    };
    const data = await api('/v1/zlibrary/login', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    form.elements.password.value = '';
    toast(`登录成功：${data.account}`);
    await loadZLibraryStatus();
  } catch(error) { toast(error.message,true); }
  finally {
    submit.disabled = false;
    submit.textContent = '登录';
  }
});
$('#tor-check').addEventListener('click', async (event) => { const button = event.currentTarget; button.disabled = true; const status = $('#tor-status'); status.textContent = 'Tor：正在检测连通性…'; try { const data = await api('/v1/zlibrary/doctor', {method:'POST'}); const state = data.reachable ? '已连接 Z-Library' : '未连接'; status.textContent = `Tor：${state}${data.authenticated ? ' · 已认证' : ' · 未认证'}`; toast(data.reachable ? 'Tor 与 Z-Library 连接正常。' : 'Tor 检查未通过。'); } catch(error) { status.textContent = `Tor：检测失败 · ${error.message}`; toast(error.message,true); } finally { button.disabled = false; } });
$('#account-picker').addEventListener('change', async (event) => { const account = event.currentTarget.value; if (!account) return; try { await api(`/v1/zlibrary/accounts/${encodeURIComponent(account)}/select`, {method:'POST'}); await loadZLibraryStatus(); toast(`已切换到账号：${account}`); } catch(error) { toast(error.message,true); await loadZLibraryStatus(); } });
document.querySelectorAll('[data-query]').forEach((button) => button.addEventListener('click', () => { const form = $('#search-form'); form.elements.query.value = button.dataset.query; form.elements.language.value = button.dataset.language || ''; form.elements.extension.value = button.dataset.extension || ''; form.requestSubmit(); }));
$('#search-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $('#search-submit');
  const status = $('#search-status');
  const sequence = ++searchSequence;
  button.disabled = true;
  status.textContent = '正在搜索…';
  try {
    const data = await api('/v1/books/search', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(Object.fromEntries(new FormData(form))),
    });
    if (sequence !== searchSequence) return;
    $('#search-results').innerHTML = (data.books || []).map((book) => `<article class="result card"><div><strong>${escaped(book.title)}</strong><p>${escaped(book.author || '作者未知')} · ${escaped(book.year || '年份未知')} · ${escaped(book.language || '语言未知')}</p><div class="chips"><span class="chip">${escaped(book.extension || '格式未知')}</span>${book.filesizeString ? `<span class="chip">${escaped(book.filesizeString)}</span>` : ''}</div></div><button data-book="${encodeURIComponent(JSON.stringify(book))}">确认下载</button></article>`).join('') || '<p class="empty">没有搜索结果。</p>';
    status.textContent = `找到 ${data.books?.length || 0} 条结果`;
    document.querySelectorAll('[data-book]').forEach((downloadButton) => {
      downloadButton.addEventListener('click', () => {
        downloadBook(JSON.parse(decodeURIComponent(downloadButton.dataset.book)), downloadButton);
      });
    });
  } catch(error) { if (sequence === searchSequence) { status.textContent = `搜索失败：${error.message}`; toast(error.message,true); } }
  finally { if (sequence === searchSequence) button.disabled = false; }
});
async function downloadBook(book, button) { if (!confirm(`确认下载《${book.title}》？这可能消耗账号下载额度。`)) return; button.disabled = true; button.textContent = '下载中…'; try { const data = await api('/v1/books/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:String(book.id),hash:String(book.hash),confirmed:true,metadata:{title:book.title,author:book.author || '',year:String(book.year || ''),language:book.language || '',format:book.extension || ''}})}); toast(`已加入书架：${data.library.path}`); await Promise.all([loadBooks(),loadTasks()]); } catch(error) { toast(error.message,true); await loadTasks().catch(() => {}); } finally { button.disabled = false; button.textContent = '确认下载'; } }
$('#convert-form').addEventListener('submit', async (event) => { event.preventDefault(); const form = event.currentTarget; try { const path = await sourcePath(form); const data = await api('/v1/convert/pdf-to-epub',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,metadata:metadata(form),mode:form.elements.mode.value})}); toast(`转换完成：${data.library.path}`); loadBooks(); } catch(error) { toast(error.message,true); } });
$('#summary-form').addEventListener('submit', async (event) => { event.preventDefault(); const form = event.currentTarget; try { const path = await sourcePath(form); const data = await api('/v1/analysis/report',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,title:form.elements.title.value,author:form.elements.author.value})}); toast(`报告已生成：${data.markdown}`); loadBooks(); } catch(error) { toast(error.message,true); } });
$('#audio-form').addEventListener('submit', async (event) => { event.preventDefault(); const form = event.currentTarget; try { const path = await sourcePath(form); const data = await api('/v1/audiosmith/audiobooks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,metadata:{title:form.elements.title.value,author:form.elements.author.value,language:'',format:''},voice:form.elements.voice.value})}); toast(`有声书项目已创建：${data.project_id}`); loadTasks(); } catch(error) { toast(error.message,true); } });
$('#settings-form').addEventListener('submit', async (event) => { event.preventDefault(); try { const payload = Object.fromEntries(new FormData(event.currentTarget)); await api('/v1/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); toast('设置已保存。'); loadBooks(); } catch(error) { toast(error.message,true); } });
(async () => { document.querySelectorAll('.source-choice').forEach((select) => syncSourceMode(select.form)); try { const health = await api('/health'); $('#connection').textContent = `本机书库已连接 · ${health.library_root}`; } catch(error) { $('#connection').textContent = '本地服务不可用'; toast(error.message,true); return; } const results = await Promise.allSettled([loadBooks(), loadTasks(), loadSettings(), loadZLibraryStatus()]); const failures = results.filter((result) => result.status === 'rejected'); if (failures.length) toast(`${failures.length} 项数据加载失败：${failures[0].reason.message}`, true); })();
