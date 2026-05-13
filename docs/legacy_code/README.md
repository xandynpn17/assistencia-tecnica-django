Arquivos arquivados de views antigas.

Estado atual:
- Nao sao importados pelas rotas ativas.
- Foram preservados apenas como referencia historica.
- O fluxo oficial do sistema usa `views.py` e `view_modules/`.
- Qualquer manutencao nova deve ocorrer nos apps ativos, nao nestes arquivos.

Objetivo:
- reduzir ruido no codigo ativo;
- evitar manutencao acidental em arquivos mortos;
- deixar claro onde termina o legado e onde comeca o fluxo atual.

Regra pratica:
- se um ajuste parece precisar deste material, primeiro confirmar se o fluxo atual nao ja tem um owner ativo em `docs/ownership_modulos.md`.
