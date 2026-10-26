// BT Ranking — service worker.
//  - Guarda css/js/icones para o app abrir rapido no celular.
//  - Manda o cabecalho que pula o aviso do ngrok gratuito em toda navegacao,
//    para o atleta so ver aquela pagina na primeira visita.
//  - Mostra /offline quando o servidor (o PC do administrador) esta fora.
// Nunca guarda paginas: elas tem dados de cada atleta.
'use strict';

var VERSAO = 'bt-ranking-3';
var PULAR_AVISO_NGROK = { 'ngrok-skip-browser-warning': '1' };
var ESTATICOS = ['/offline', '/static/icone.svg', '/static/icone-192.png'];

self.addEventListener('install', function (evento) {
  evento.waitUntil(
    caches.open(VERSAO).then(function (cache) {
      return Promise.all(ESTATICOS.map(function (url) {
        // fetch com o cabecalho, e nao cache.addAll: sem ele o ngrok devolveria
        // a pagina de aviso no lugar do arquivo.
        return fetch(url, { headers: PULAR_AVISO_NGROK }).then(function (resposta) {
          if (resposta.ok) return cache.put(url, resposta);
        });
      }));
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (evento) {
  evento.waitUntil(
    caches.keys().then(function (nomes) {
      return Promise.all(nomes.filter(function (nome) { return nome !== VERSAO; })
        .map(function (nome) { return caches.delete(nome); }));
    }).then(function () { return self.clients.claim(); })
  );
});

function servidorFora(resposta) {
  // O ngrok responde com um erro proprio (ERR_NGROK_...) quando o PC esta desligado.
  return resposta.headers.has('ngrok-error-code');
}

self.addEventListener('fetch', function (evento) {
  var pedido = evento.request;
  var url = new URL(pedido.url);
  if (pedido.method !== 'GET' || url.origin !== self.location.origin) return;

  if (pedido.mode === 'navigate') {
    // redirect 'manual': o navegador segue os redirecionamentos do servidor
    // (ex.: /inicio -> /entrar) como faria sem o service worker.
    evento.respondWith(
      fetch(pedido.url, { headers: PULAR_AVISO_NGROK, credentials: 'same-origin', redirect: 'manual' })
        .then(function (resposta) {
          return servidorFora(resposta) ? caches.match('/offline') : resposta;
        })
        .catch(function () { return caches.match('/offline'); })
    );
    return;
  }

  if (url.pathname.startsWith('/static/')) {
    evento.respondWith(
      caches.open(VERSAO).then(function (cache) {
        return cache.match(pedido).then(function (guardado) {
          if (guardado) return guardado;
          return fetch(pedido.url, { headers: PULAR_AVISO_NGROK }).then(function (resposta) {
            if (resposta.ok) cache.put(pedido, resposta.clone());
            return resposta;
          });
        });
      })
    );
  }
});
