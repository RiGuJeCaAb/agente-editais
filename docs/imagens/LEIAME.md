# Imagens

Provas em imagem de alterações visuais, para se poder comparar sem ter de
correr duas versões lado a lado.

| Ficheiro | O que mostra |
|---|---|
| `fundo-antes-filamentos.jpg` | O fundo da televisão na 0.21.0: vinte e seis linhas traçadas com 0,6 a 2,2 px |
| `fundo-depois-lencois.jpg` | O mesmo instante na 0.22.0: onze faixas preenchidas, com as margens em fases diferentes |

As duas são do **mesmo instante** da animação, e é por isso que se podem
comparar. A página foi renderizada em Chromium com o `requestAnimationFrame`
substituído por um que chama a função de desenho exatamente duas vezes — a
primeira com tempo 0, para fixar o instante inicial, a segunda com o tempo que
se quer fotografar. Assim corre o código verdadeiro e a fotografia é
reproduzível, em vez de apanhar o que calhar.

O ecrã de arranque (`#arranque`) tem `z-index: 50` e fundo opaco: sem o esconder,
fotografa-se a cortina e não o fundo. Custou uma conclusão errada antes de se
perceber.
