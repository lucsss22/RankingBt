// BT Ranking — o pouco de JavaScript do app. Tudo funciona sem ele; aqui so
// fica mais rapido (tema sem recarregar, selects que atualizam sozinhos).
(function () {
  'use strict';

  var COR_BARRA = { a: '#F5EFE3', b: '#0F1613' };

  function aplicarTema(tema) {
    document.documentElement.setAttribute('data-tema', tema);
    var seguro = location.protocol === 'https:' ? '; secure' : '';
    document.cookie = 'bt_tema=' + tema + '; path=/; max-age=31536000; samesite=lax' + seguro;
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', COR_BARRA[tema]);
    document.querySelectorAll('[data-alternar-tema]').forEach(function (botao) {
      botao.setAttribute('aria-pressed', tema === 'b' ? 'true' : 'false');
      var campo = botao.form && botao.form.querySelector('input[name="tema"]');
      if (campo) campo.value = tema === 'b' ? 'a' : 'b';
    });
  }

  document.addEventListener('click', function (evento) {
    var botaoTema = evento.target.closest('[data-alternar-tema]');
    if (botaoTema) {
      evento.preventDefault();
      var atual = document.documentElement.getAttribute('data-tema');
      aplicarTema(atual === 'b' ? 'a' : 'b');
      return;
    }

    var botaoCopiar = evento.target.closest('[data-copiar]');
    if (botaoCopiar && navigator.clipboard) {
      navigator.clipboard.writeText(botaoCopiar.getAttribute('data-copiar')).then(function () {
        botaoCopiar.textContent = 'Link copiado';
      });
    }
  });

  // Selects que mudam as opcoes seguintes (categoria -> chave -> rodada).
  // submit() e nao requestSubmit(): o campo de rodada ainda vazio e
  // obrigatorio e barraria o envio.
  document.addEventListener('change', function (evento) {
    if (evento.target.matches('[data-auto-enviar]') && evento.target.form) {
      evento.target.form.submit();
    }
  });

  // Busca na ITF em segundo plano: pergunta ao servidor ate terminar e
  // recarrega a pagina com o resultado.
  var aguardando = document.querySelector('[data-aguardar]');
  if (aguardando && window.fetch) {
    var tarefa = aguardando.getAttribute('data-aguardar');
    var destino = new URL(aguardando.getAttribute('data-voltar') || location.pathname, location.href);
    var consultar = function () {
      fetch('/tarefa?nome=' + encodeURIComponent(tarefa), {
        credentials: 'same-origin',
        headers: { 'ngrok-skip-browser-warning': '1' }
      })
        .then(function (resposta) { return resposta.json(); })
        .then(function (estado) {
          if (estado.rodando) { setTimeout(consultar, 3000); return; }
          if (destino.pathname + destino.search === location.pathname + location.search) location.reload();
          else location.replace(destino.href);
        })
        .catch(function () { setTimeout(consultar, 6000); });
    };
    setTimeout(consultar, 3000);
  }

  // Nome com autocompletar do ranking (dupla simulada da tierlist). Escolher
  // um nome guarda o playerId no campo escondido e esconde rank/pontos, que
  // passam a vir do ranking do dia. Mexer no texto desfaz a escolha.
  function textoEscolhido(jogador) {
    return 'No ranking: ' + (jogador.rank ? '#' + jogador.rank : 'sem ranking') + ' · ' +
      jogador.pontos + ' pts' + (jogador.pais ? ' · ' + jogador.pais : '');
  }

  function iniciarBusca(grupo) {
    var campo = grupo.querySelector('[data-buscar-ranking]');
    var lista = grupo.querySelector('.sugestoes');
    var escondido = grupo.querySelector('input[type="hidden"][name^="itf"]');
    var aviso = grupo.querySelector('[data-escolhido]');
    var avisoTexto = grupo.querySelector('[data-escolhido-texto]');
    var manuais = grupo.querySelector('[data-campos-manuais]');
    var souEu = grupo.querySelector('[data-sou-eu]');
    if (!campo || !lista || !escondido || !window.fetch) return;
    var genero = campo.getAttribute('data-buscar-ranking');
    var achados = [];
    var ativo = -1;
    var pedido = 0;
    var espera = null;

    function fechar() {
      lista.hidden = true;
      lista.textContent = '';
      campo.setAttribute('aria-expanded', 'false');
      campo.removeAttribute('aria-activedescendant');
      ativo = -1;
    }

    function marcar(jogador) {
      escondido.value = jogador ? jogador.id : '';
      aviso.hidden = !jogador;
      avisoTexto.textContent = jogador ? textoEscolhido(jogador) : '';
      manuais.hidden = !!jogador;
      if (jogador) manuais.querySelectorAll('input').forEach(function (entrada) { entrada.value = ''; });
    }

    function escolher(jogador) {
      campo.value = jogador.nome;
      marcar(jogador);
      fechar();
    }

    function destacar(indice) {
      var itens = lista.querySelectorAll('[data-indice]');
      if (!itens.length) return;
      ativo = (indice + itens.length) % itens.length;
      itens.forEach(function (item, i) { item.setAttribute('aria-selected', i === ativo ? 'true' : 'false'); });
      campo.setAttribute('aria-activedescendant', itens[ativo].id);
      itens[ativo].scrollIntoView({ block: 'nearest' });
    }

    function mostrar(jogadores) {
      achados = jogadores;
      lista.textContent = '';
      ativo = -1;
      if (!jogadores.length) {
        var vazio = document.createElement('li');
        vazio.className = 'sugestao-vazia';
        vazio.setAttribute('role', 'option');
        vazio.setAttribute('aria-disabled', 'true');
        vazio.textContent = 'Ninguém com esse nome no ranking. Pode adicionar com o nome digitado.';
        lista.appendChild(vazio);
      }
      jogadores.forEach(function (jogador, i) {
        var item = document.createElement('li');
        item.id = lista.id + '-' + i;
        item.setAttribute('role', 'option');
        item.setAttribute('aria-selected', 'false');
        item.setAttribute('data-indice', i);
        var nome = document.createElement('span');
        nome.className = 'sugestao-nome';
        nome.textContent = jogador.nome;
        var info = document.createElement('span');
        info.className = 'legenda';
        info.textContent = (jogador.pais ? jogador.pais + ' · ' : '') + jogador.pontos + ' pts';
        var rank = document.createElement('span');
        rank.className = 'numero';
        rank.textContent = jogador.rank ? '#' + jogador.rank : '—';
        item.appendChild(nome);
        item.appendChild(rank);
        item.appendChild(info);
        lista.appendChild(item);
      });
      lista.hidden = false;
      campo.setAttribute('aria-expanded', 'true');
    }

    function buscar() {
      var texto = campo.value.trim();
      var este = ++pedido;
      if (texto.length < 2) { fechar(); return; }
      fetch('/ranking/buscar?genero=' + encodeURIComponent(genero) + '&q=' + encodeURIComponent(texto), {
        credentials: 'same-origin',
        headers: { 'ngrok-skip-browser-warning': '1' }
      })
        .then(function (resposta) { return resposta.json(); })
        .then(function (dados) {
          if (este === pedido && document.activeElement === campo) mostrar(dados.jogadores || []);
        })
        .catch(fechar);
    }

    campo.addEventListener('input', function () {
      if (escondido.value) marcar(null);
      clearTimeout(espera);
      espera = setTimeout(buscar, 200);
    });
    campo.addEventListener('keydown', function (evento) {
      if (lista.hidden) return;
      if (evento.key === 'ArrowDown') { evento.preventDefault(); destacar(ativo + 1); }
      else if (evento.key === 'ArrowUp') { evento.preventDefault(); destacar(ativo - 1); }
      else if (evento.key === 'Escape') { fechar(); }
      else if (evento.key === 'Enter' && achados.length) {
        // Enter com a lista aberta escolhe (o destacado ou o primeiro) em vez de enviar.
        evento.preventDefault();
        escolher(achados[ativo >= 0 ? ativo : 0]);
      }
    });
    campo.addEventListener('blur', function () { setTimeout(fechar, 150); });
    // No celular o teclado cobre a metade de baixo da tela: sobe o campo para
    // as sugestoes aparecerem embaixo dele.
    campo.addEventListener('focus', function () {
      if (campo.readOnly || !window.matchMedia('(max-width: 699px)').matches) return;
      var suave = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      setTimeout(function () {
        campo.closest('.campo').scrollIntoView({ block: 'start', behavior: suave ? 'smooth' : 'auto' });
      }, 300);
    });
    // Sem isso o toque na lista tira o foco do campo e ela fecha antes do clique.
    lista.addEventListener('mousedown', function (evento) { evento.preventDefault(); });
    lista.addEventListener('click', function (evento) {
      var item = evento.target.closest('[data-indice]');
      if (item) escolher(achados[+item.getAttribute('data-indice')]);
    });

    if (souEu) {
      var eu = JSON.parse(souEu.getAttribute('data-sou-eu'));
      var aplicarEu = function () {
        campo.readOnly = souEu.checked;
        if (souEu.checked) {
          escolher(eu);
        } else if (escondido.value === String(eu.id)) {
          campo.value = '';
          marcar(null);
        }
      };
      souEu.addEventListener('change', function () {
        aplicarEu();
        if (!souEu.checked) campo.focus();
      });
      if (souEu.checked) aplicarEu();
    }
  }

  document.querySelectorAll('[data-atleta-ranking]').forEach(iniciarBusca);

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js').catch(function () { /* sem app offline, segue normal */ });
    });
  }
})();
