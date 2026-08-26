// Pequenos comportamentos client-side
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.copy-btn');
  if (!btn) return;
  const id = btn.dataset.copyTarget;
  const el = document.getElementById(id);
  if (!el) return;
  el.select();
  document.execCommand('copy');
  btn.textContent = '✅ Copiado';
  setTimeout(() => btn.textContent = '📋 Copiar', 1500);
});
