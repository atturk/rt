// Pagina Scarica: evidenzia il sistema di chi visita e, se GitHub risponde, porta i link
// all'ultima release (la pagina compilata ha già i link alla versione in VERSION).
(function () {
  var ua = navigator.userAgent || '';
  var os = /Mac/i.test(ua) && !/iPhone|iPad/i.test(ua) ? 'mac' : /Win/i.test(ua) ? 'win' : '';
  if (os) {
    var card = document.querySelector('.os[data-os="' + os + '"]');
    if (card) {
      card.classList.add('tuo');
      card.parentNode.insertBefore(card, card.parentNode.firstChild);
    }
  }

  if (!window.fetch) return;
  fetch('https://api.github.com/repos/atturk/rt/releases/latest', { headers: { Accept: 'application/vnd.github+json' } })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (rel) {
      if (!rel || !rel.assets) return;
      var trova = { mac: /-macos-arm64\.dmg$/, win: /-windows-x64-setup\.exe$/ };
      Object.keys(trova).forEach(function (k) {
        var a = rel.assets.filter(function (x) { return trova[k].test(x.name); })[0];
        if (!a) return;
        var link = document.querySelector('[data-file="' + k + '"]');
        var nome = document.querySelector('[data-nome="' + k + '"]');
        if (link) link.href = a.browser_download_url;
        if (nome) nome.textContent = a.name + ' · ' + Math.round(a.size / 1048576) + ' MB';
      });
      var v = document.querySelector('[data-versione]');
      if (v && rel.tag_name) v.textContent = rel.tag_name.replace(/^v/, '');
    })
    .catch(function () {});
})();
