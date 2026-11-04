import assert from 'node:assert/strict';
import { test } from 'node:test';
import { NoteEditor } from '../src/midimcp/web/editor.js';
class Element {
  constructor(tag) { this.tagName=tag.toUpperCase();this.children=[];this.attributes={};this.scrollTop=0;this.scrollLeft=0;this.clientHeight=400;this.classList={add(){},toggle(){}}; }
  setAttribute(key,value){this.attributes[key]=String(value);if(key==='value')this.value=String(value);}
  getAttribute(key){return this.attributes[key]??null;}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  addEventListener(){}
  removeEventListener(){}
  contains(n){return n===this||this.children.some(c=>c.contains?.(n));}
  focus(){document.activeElement=this;}
  get options(){return this.children;}
}
globalThis.document={createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag),activeElement:null};
const view=(id='a',revision=1,pitch=74)=>({projectId:id,revision,timing:{ppq:960,ticksPerBar:3840,totalTicks:7680},brief:{locks:[]},score:{tracks:[{id:'t',name:'Track',automation:{expression:[{tick:0,value:80}]},notes:[{id:'n',pitch,startTick:0,durationTicks:960,velocity:80}]}]}});
function setup(options={}){const container=new Element('section');return new NoteEditor({container,api:{},...options});}
test('repeated null views are safe and initial viewport centers on track pitch',()=>{const e=setup();e.setView(null);e.setView(null);e.setView(view());assert.ok(e.scroll.scrollTop<700);e.setView(null);assert.equal(e.cursor,null);});
test('history buttons reflect pending and available history',async()=>{const e=setup();e.setView(view());assert.equal(e.undoButton.disabled,true);let done;const pending=e.mutate(()=>new Promise(r=>done=r));assert.equal(e.undoButton.disabled,true);done({revision:2});await pending;assert.equal(e.undoButton.disabled,false);assert.equal(e.pending,false);});
test('late save completion cannot poison a different song history',async()=>{const notifications=[];const e=setup({onChange:r=>notifications.push(r)});e.setView(view());let done;const pending=e.mutate(()=>new Promise(r=>done=r));e.setView(view('b'));done({revision:9});await pending;assert.deepEqual(e.undo,[]);assert.notEqual(e.ownRevision,9);assert.equal(e.view.projectId,'b');assert.equal(notifications[0].projectId,'a');});
test('extension preference and error status survive render/draw',()=>{const e=setup();e.setView(view());e.extend.checked=true;e.extend.onchange();e.say('Protected selection');e.render();assert.equal(e.extend.checked,true);assert.equal(e.status.textContent,'Protected selection');e.draw();assert.equal(e.status.textContent,'Protected selection');});
test('switching tracks centers visible pitch and selects whole track',()=>{const e=setup();const v=view();v.score.tracks.push({...v.score.tracks[0],id:'high',notes:[{...v.score.tracks[0].notes[0],id:'high-note',pitch:100}]});e.setView(v);e.selectTrack('high');assert.ok(e.scroll.scrollTop<300);assert.deepEqual([...e.selected],['high-note']);});
function descendants(node){return [node,...node.children.flatMap(descendants)];}
test('automation warning is visible before editing, and empty AI copy is rejected',()=>{const e=setup();e.setView(view());const nodes=descendants(e.container);assert.ok(nodes.some(n=>n.textContent?.includes('leave those curves at their original ticks')));nodes.find(n=>n.textContent==='Copy selection for AI').onclick();assert.equal(e.status.textContent,'Select notes first.');});
test('loop saves participate in undo history',async()=>{const e=setup();e.api.setArrangement=async()=>({revision:2});e.setView(view());e.selectTrack('t');await descendants(e.container).find(n=>n.textContent==='Loop selected passage').onclick();await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(e.undo,[1]);});
test('external same-song revisions invalidate pending save history',async()=>{const e=setup();e.setView(view());let done;const pending=e.mutate(()=>new Promise(r=>done=r));e.setView(view('a',3));done({revision:2});await pending;assert.deepEqual(e.undo,[]);assert.equal(e.view.revision,3);});
test('drag previews reuse the note rectangle index without DOM queries',()=>{const e=setup();const v=view();v.score.tracks[0].notes=Array.from({length:1000},(_,i)=>({...v.score.tracks[0].notes[0],id:`n${i}`}));e.setView(v);let queries=0;e.scroll.querySelectorAll=()=>{queries++;throw new Error('Unexpected DOM scan');};e.previewGeometry(e.notes.map(n=>({...n,startTick:960})));assert.equal(queries,0);assert.equal(e.noteRects.size,1000);assert.equal(e.noteRects.get('n999').getAttribute('x'),String(e.x(960)));});
test('phrase factor and velocity sliders update their numeric controls',()=>{const e=setup();e.mode='phrase';e.setView(view());const labels=descendants(e.container).filter(n=>n.tagName==='LABEL');const field=label=>labels.find(n=>n.textContent===label).children[0];const factor=field('Factor'),factorRange=field('Time scaling slider'),velocity=field('Velocity'),velocityRange=field('Loudness slider');factorRange.value='1.5';factorRange.oninput();assert.equal(factor.value,'1.5');velocityRange.value='110';velocityRange.oninput();assert.equal(velocity.value,'110');assert.equal(factorRange.max,3);assert.equal(factor.max,undefined);});
test('separate sticky ruler shares time geometry and clamps seeks',()=>{const seeks=[];const e=setup({onSeek:tick=>seeks.push(tick)});e.setView(view());const ruler=e.scroll.children[0],roll=e.scroll.children[1];assert.equal(ruler.getAttribute('class'),'editor-ruler');assert.equal(ruler.getAttribute('width'),roll.getAttribute('width'));ruler.getBoundingClientRect=()=>({left:100});ruler.onclick({clientX:100+e.x(3840)});ruler.onclick({clientX:0});ruler.onclick({clientX:100000});assert.deepEqual(seeks,[3840,0,7680]);});

test('note end handle snaps an off-grid end to the grid without moving its start',()=>{
  const e=setup();const v=view();v.score.tracks[0].notes[0].durationTicks=900;e.setView(v);
  const handle=descendants(e.container).find(n=>n.getAttribute('data-resize-note')==='n');
  assert.ok(handle,'notes expose a dedicated resize target');
  const roll=e.scroll.children[1];roll.getBoundingClientRect=()=>({left:0,top:0});roll.setPointerCapture=()=>{};
  let edited;e.apply=notes=>{edited=notes;};
  const x=e.x(900)-2,y=24+(127-74)*14+6;
  e.pointer({button:0,target:handle,clientX:x,clientY:y,pointerId:1,preventDefault(){}},roll);
  e.gesture.move({clientX:x+10,clientY:y-20});
  assert.equal(e.noteRects.get('n').getAttribute('width'),'60');
  assert.equal(handle.getAttribute('x'),'97');
  e.gesture.up();
  assert.equal(edited[0].durationTicks,1200);
  assert.equal(edited[0].startTick,0);
  assert.equal(edited[0].pitch,74);
});

test('protected notes do not expose an active resize handle',()=>{
  const e=setup();const v=view();v.brief.locks=[{id:'lock',trackId:'t'}];e.setView(v);
  assert.equal(descendants(e.container).filter(n=>n.getAttribute('data-resize-note')).length,0);
});

test('performance applies once and supports undo without changing another track',async()=>{
  const calls=[];const e=setup();e.api.applyPerformance=async(...args)=>{calls.push(args);return {revision:2};};e.setView(view());
  descendants(e.container).find(n=>n.textContent==='Apply flute performance').onclick();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(calls.length,1);
  assert.equal(calls[0][0],'a');assert.equal(calls[0][1],'t');
  assert.equal(calls[0][2].expectedRevision,1);
  assert.equal(calls[0][2].breathTicks,120);
  assert.deepEqual(e.undo,[1]);
});

test('pedaling a selected note leaves room after note-off and supports undo', async () => {
  const editor = setup({api: {
    setAutomation: async (project, track, body) => {
      assert.equal(project, 'a');
      assert.equal(track, 't');
      assert.deepEqual(body, {
        expectedRevision: 1, lane: 'sustain', startTick: 0, endTick: 1200,
        points: [{tick: 0, value: 127}, {tick: 1199, value: 0}],
      });
      return {revision: 2};
    },
  }});
  editor.setView(view());
  editor.selectTrack('t');
  const buttons = descendants(editor.container);
  buttons.find(node => node.textContent === 'Use selected notes').onclick();
  await buttons.find(node => node.textContent === 'Apply sustain pedal').onclick();
  assert.deepEqual(editor.undo, [1]);
});

test('sampled flute release reset sends null and supports undo', async () => {
  const editor = setup({api: {
    updateTrack: async (project, track, body) => {
      assert.equal(project, 'a');
      assert.equal(track, 't');
      assert.deepEqual(body, {expectedRevision: 1, releaseSeconds: null});
      return {revision: 2};
    },
  }});
  const song = view();
  song.score.tracks[0].sampler = {patchId: 'vsco-flute-controlled'};
  song.score.tracks[0].releaseSeconds = 1.1;
  editor.setView(song);
  await descendants(editor.container).find(node => node.textContent === 'Reset flute release').onclick();
  assert.deepEqual(editor.undo, [1]);
});
