export function projectPath(raw) {
  const path=String(raw).replaceAll('\\','/');
  const parts=path.split('/');
  if(parts.some(p=>!p||p==='.'||p==='..'||p.includes(':')||/[?#%\u0000-\u001f]/.test(p)))throw new Error('路径须为项目内的相对路径');
  return parts.map(encodeURIComponent).join('/');
}
export function resultPath(raw) {
  const path=projectPath(raw);
  if(!path.startsWith('outputs/')||!path.endsWith('/result.json'))throw new Error('请选择 outputs 目录下的 result.json');
  return path;
}
export function percentage(value) {
  return typeof value==='number'&&Number.isFinite(value)?`${(value*100).toFixed(1)}%`:'未评测';
}
