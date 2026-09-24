# Instruções para revisão

As regras completas estão em `AGENTS.md`, na raiz. O essencial, para quem só lê
este ficheiro:

- **Responde em português europeu.** Registo técnico, nunca português do Brasil.
- **Sem emojis** nos comentários de revisão.
- Este agente publica editais municipais numa televisão. Um edital que não
  aparece, ou que aparece com o assunto trocado, é uma falha de afixação com
  consequência legal. É a classe de defeito que interessa acima de todas.
- A seguir, por ordem: estado em disco que fica a meio; janelas entre conferir e
  agir; pressupostos sobre o ambiente (Windows, duplo clique, `sys.stdin` a
  `None`, sem LibreOffice); e memória, porque se trabalha com imagens de
  3840×2160.
- Um teste novo tem de falhar contra o código anterior. Se passa dos dois lados,
  não prova nada.
- Alargar uma lista de exclusão numa heurística é o defeito mais perigoso do
  repositório: o que ela passa a excluir a mais desaparece em silêncio, sem erro.
- O `CHANGELOG.md` está por ordem ascendente. Secção nova vai para o fim.
- **Não comentes** preferências de estilo que o `ruff` não impõe, renomeações sem
  razão, nem anotações de tipo onde o `mypy` já está satisfeito.
