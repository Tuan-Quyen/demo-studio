// Tiny "framework": re-renders the list by REPLACING text data and node children, like React would,
// so the mask must survive node churn. No attribute is added by the app on sensitive nodes.
const root = document.getElementById('root');
const names = ['Initech', 'Globex', 'Umbrella', 'Hooli', 'Stark Ind', 'Wayne Ent', 'Soylent', 'Cyberdyne', 'Tyrell', 'Wonka',
               'Vandelay', 'Pied Piper', 'Dunder', 'Oscorp', 'Massive'];
function row(i) {
  const d = document.createElement('div'); d.className = 'row';
  const b = document.createElement('b'); b.textContent = names[i % names.length] + ' #' + i;
  const s = document.createElement('span'); s.textContent = 'Paid';
  d.append(b, s);
  if (i === 11) {
    const k = document.createElement('code'); k.className = 'keybox'; k.id = 'apikey';
    k.setAttribute('data-sensitive', ''); k.textContent = 'sk_live_51H8ZQa9XbCdEf';
    d.append(k);
  }
  return d;
}
for (let i = 0; i < 22; i++) root.append(row(i));
const inner = document.getElementById('inner');
for (let i = 0; i < 30; i++) {
  const d = document.createElement('div');
  d.textContent = i === 12 ? 'Contact grace.hopper@navy.example for access' : 'Inner row ' + i;
  inner.append(d);
}
let n = 0;
setInterval(() => {                       // re-render churn on non-sensitive nodes + a sensitive one
  n++;
  document.getElementById('synced').textContent = 'synced ' + n;
  const old = root.children[3]; root.replaceChild(row(3 + (n % 2) * 0), old);
  const key = document.getElementById('apikey');
  if (key && n % 3 === 0) key.firstChild.data = 'sk_live_51H8ZQa9XbCdEf';   // same text, new data write
}, 400);
setTimeout(() => {                        // late toast containing an email (regex only, no data-sensitive)
  const t = document.createElement('div'); t.className = 'toast'; t.id = 'toast';
  t.textContent = 'Receipt sent to bob.builder@corp.example';
  document.body.appendChild(t);
}, 2000);
