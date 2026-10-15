// Requires mathjax-full 3.2.2 and sharp. Run with the bundled Node runtime.
const fs = require('fs');
const path = require('path');
const sharp = require('sharp');
const {mathjax} = require('mathjax-full/js/mathjax.js');
const {TeX} = require('mathjax-full/js/input/tex.js');
const {SVG} = require('mathjax-full/js/output/svg.js');
const {liteAdaptor} = require('mathjax-full/js/adaptors/liteAdaptor.js');
const {RegisterHTMLHandler} = require('mathjax-full/js/handlers/html.js');
const {AllPackages} = require('mathjax-full/js/input/tex/AllPackages.js');
const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);
const mathDoc = mathjax.document('', {
  InputJax: new TeX({packages: AllPackages}),
  OutputJax: new SVG({fontCache: 'local'})
});
const expressions = {
  persona: String.raw`h_i=0.60\,p_i+0.40\,\ell_i`,
  taylor: String.raw`r^{\mathrm{target}}_{i,t}=r^{\ast}+\pi_t+\alpha_i(\pi_t-\pi^{\ast})+\beta_i x_t+\gamma_i(f_t-f^{\ast})`,
  smooth: String.raw`r_{i,t}=\rho\,r_{t-1}+(1-\rho)\,r^{\mathrm{target}}_{i,t}`,
  f1: String.raw`F_1=\frac{2\,\mathrm{TP}}{2\,\mathrm{TP}+\mathrm{FP}+\mathrm{FN}}`
};
(async()=>{
  const dir = process.argv[2]; fs.mkdirSync(dir,{recursive:true});
  const sizes = {};
  for (const [id,latex] of Object.entries(expressions)) {
    const html = adaptor.outerHTML(mathDoc.convert(latex,{display:true}));
    let svg = html.slice(html.indexOf('<svg'),html.indexOf('</svg>')+6);
    if (!svg.includes('xmlns=')) svg=svg.replace('<svg ', '<svg xmlns="http://www.w3.org/2000/svg" ');
    svg=svg.replace(/(width|height)="([0-9.]+)(ex|em)"/g,(_,a,n)=>`${a}="${Math.round(parseFloat(n)*8.5)}px"`).replace(/currentColor/g,'#000000');
    const file = path.join(dir,`equation_${id}.png`);
    const info = await sharp(Buffer.from(svg),{density:300}).png().toFile(file);
    sizes[id]={width_inches:info.width/300,height_inches:info.height/300};
  }
  fs.writeFileSync(path.join(dir,'equation_sizes.json'),JSON.stringify(sizes,null,2));
})().catch(e=>{console.error(e);process.exit(1)});
