import { useCallback, useEffect, useRef, useState } from 'react';
import { RotateCcw, Scan, ZoomIn, ZoomOut } from 'lucide-react';
import {
  clamp, defaultOrbit, dot, fieldPoint, lensUniforms, orbitCamera,
  projectToScreen, type CameraBasis, type CameraPreset, type Orbit, type Vec3,
} from './football3dMath';
import '../football-field-3d.css';

/** Source-facing types: coordinates in yards, not arbitrary screen positions. */
export interface Field3DPlayer {
  id: string;
  jersey?: string | null;
  name?: string | null;
  side: 'offense' | 'defense' | null;
  team?: string | null;
  x: number;
  y: number;
}
export interface Field3DBall { x: number; y: number; }
export interface Field3DTrail {
  id: string;
  from: readonly [number,number];
  to: readonly [number,number];
  side: 'offense'|'defense'|null;
}
interface Props {
  players: readonly Field3DPlayer[];
  ball: Field3DBall | null;
  trails: readonly Field3DTrail[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  preset: CameraPreset;
  focus?: Vec3;
  showLabels?: boolean;
  showTrails?: boolean;
  showNearest?: boolean;
  snapPlayers?: readonly Field3DPlayer[];
  showSnap?: boolean;
  synthetic?: boolean;
  onUnsupported?: () => void;
}
type Color = readonly [number,number,number];
const GREEN:Color = [0.105,0.315,0.255];
const STRIPE:Color = [0.125,0.355,0.29];
const WHITE:Color = [0.72,0.85,0.78];
const OFFENSE:Color = [0.32,0.7,0.94];
const DEFENSE:Color = [0.96,0.43,0.41];
const UNKNOWN:Color = [0.7,0.77,0.81];
const SELECT:Color = [1.0,0.82,0.40];
const VERTEX = `#version 300 es
in vec3 a_position;
in vec3 a_color;
uniform vec3 u_eye;
uniform vec3 u_right;
uniform vec3 u_up;
uniform vec3 u_forward;
uniform vec4 u_lens;
out vec3 v_color;
void main() {
  vec3 d = a_position - u_eye;
  float z = dot(d, u_forward);
  gl_Position = vec4(dot(d,u_right)*u_lens.x, dot(d,u_up)*u_lens.y,
                      u_lens.z*z + u_lens.w, z);
  v_color = a_color;
}`;
const FRAGMENT = `#version 300 es
precision mediump float;
in vec3 v_color;
out vec4 out_color;
void main(){ out_color=vec4(v_color,1.0); }`;

class Mesh {
  values:number[]=[];
  vertex(p:Vec3,c:Color){this.values.push(p[0],p[1],p[2],c[0],c[1],c[2]);}
  triangle(a:Vec3,b:Vec3,c:Vec3,color:Color){
    this.vertex(a,color);this.vertex(b,color);this.vertex(c,color);
  }
  quad(a:Vec3,b:Vec3,c:Vec3,d:Vec3,color:Color){
    this.triangle(a,b,c,color);this.triangle(a,c,d,color);
  }
  rect(x0:number,z0:number,x1:number,z1:number,h:number,color:Color){
    this.quad([x0,h,z0],[x1,h,z0],[x1,h,z1],[x0,h,z1],color);
  }
  line(x0:number,z0:number,x1:number,z1:number,w:number,h:number,color:Color){
    const dx=x1-x0,dz=z1-z0;const l=Math.hypot(dx,dz);
    if(l<1e-6)return;
    const px=-dz/l*w/2,pz=dx/l*w/2;
    this.quad([x0+px,h,z0+pz],[x1+px,h,z1+pz],[x1-px,h,z1-pz],[x0-px,h,z0-pz],color);
  }
  ring(x:number,z:number,r:number,w:number,h:number,color:Color){
    const n=28;
    for(let i=0;i<n;i++){
      const a=i*2*Math.PI/n,b=(i+1)*2*Math.PI/n;
      this.line(x+Math.cos(a)*r,z+Math.sin(a)*r,
                x+Math.cos(b)*r,z+Math.sin(b)*r,w,h,color);
    }
  }
  cylinder(x:number,z:number,r:number,h:number,y0:number,color:Color){
    const n=10;
    for(let i=0;i<n;i++){
      const a=i*2*Math.PI/n,b=(i+1)*2*Math.PI/n;
      const x0=x+Math.cos(a)*r,z0=z+Math.sin(a)*r;
      const x1=x+Math.cos(b)*r,z1=z+Math.sin(b)*r;
      const shade = 0.75 + 0.25 * Math.max(0,Math.cos(a+0.5));
      const side:Color=[color[0]*shade,color[1]*shade,color[2]*shade];
      this.quad([x0,y0,z0],[x1,y0,z1],[x1,y0+h,z1],[x0,y0+h,z0],side);
      this.triangle([x,y0+h,z],[x0,y0+h,z0],[x1,y0+h,z1],color);
    }
  }
}
function buildTurf():Float32Array {
  const m=new Mesh();
  m.rect(-60,-26.65,60,26.65,0, GREEN);
  for(let yard=0;yard<120;yard+=10){
    const x=yard-60;
    m.rect(x,-26.65,x+5,26.65,.006, STRIPE);
  }
  m.rect(-60,-26.65,-50,26.65,.012,[0.13,0.25,0.36]);
  m.rect(50,-26.65,60,26.65,.012,[0.34,0.20,0.23]);
  for(let yard=10;yard<=110;yard+=5){
    const x=yard-60;
    const major=yard%10===0;
    m.line(x,-26.65,x,26.65,major?.16:.075,.045, WHITE);
    if(major){
      for(const z of [-15.5,15.5]){
        m.line(x-.46,z,x+.46,z,.12,.06, WHITE);
      }
    }
  }
  for(const z of [-26.65,26.65]){
    m.line(-60,z,60,z,.18,.06,WHITE);
  }
  m.line(-60,-26.65,-60,26.65,.18,.06,WHITE);
  m.line(60,-26.65,60,26.65,.18,.06,WHITE);
  m.line(-50,-26.65,-50,26.65,.3,.08,WHITE);
  m.line(50,-26.65,50,26.65,.3,.08,WHITE);
  // Low field side panels establish physical depth, not a floating 2D texture.
  for(const z of [-26.8,26.8]){
    m.quad([-60,-.4,z],[60,-.4,z],[60,0,z],[-60,0,z],[.065,.16,.15]);
  }
  return new Float32Array(m.values);
}
function safeField(x:number,y:number,height:number):Vec3|null {
  if(!Number.isFinite(x)||!Number.isFinite(y)||x<0||x>120||y<0||y>53.3)return null;
  return fieldPoint(x,y,height);
}
function buildActors(p:Props):Float32Array {
  const m=new Mesh();
  if(p.showTrails!==false){
    for(const seg of p.trails){
      const a=safeField(seg.from[0],seg.from[1],.09);
      const b=safeField(seg.to[0],seg.to[1],.09);
      if(!a||!b||Math.hypot(a[0]-b[0],a[2]-b[2])>9)continue;
      const color=seg.side==='offense'?OFFENSE:seg.side==='defense'?DEFENSE:UNKNOWN;
      m.line(a[0],a[2],b[0],b[2],.24,.09,color);
    }
  }
  if(p.showSnap && p.snapPlayers?.length){
    for(const observed of p.snapPlayers){
      const pos=safeField(observed.x,observed.y,.13);
      if(pos)m.ring(pos[0],pos[2],1.03,.11,.13,[.78,.83,.86]);
    }
  }
  const focused=p.players.find(x=>x.id===p.selectedId&&x.side);
  const nearest=focused && p.showNearest
    ? p.players.filter(x=>x.side&&x.side!==focused.side)
        .map(x=>({p:x,d:Math.hypot(x.x-focused.x,x.y-focused.y)}))
        .sort((a,b)=>a.d-b.d)[0]
    : null;
  if(focused&&nearest){
    const a=safeField(focused.x,focused.y,.18);
    const b=safeField(nearest.p.x,nearest.p.y,.18);
    if(a&&b){
      m.line(a[0],a[2],b[0],b[2],.15,.20,SELECT);
      m.ring(b[0],b[2],1.2,.15,.15,SELECT);
    }
  }
  for(const player of p.players){
    const world=safeField(player.x,player.y,0);
    if(!world)continue;
    const [x,,z]=world;
    const color=player.side==='offense'?OFFENSE:player.side==='defense'?DEFENSE:UNKNOWN;
    m.cylinder(x,z,.82,.035,.10,[.025,.085,.10]); // foot shadow
    m.cylinder(x,z,.55,1.56,.15,color); // torso and shoulders
    m.cylinder(x,z,.43,.58,1.71,player.side==='defense'?[.94,.79,.77]:[.83,.91,1]);
    if(player.id===p.selectedId){
      m.ring(x,z,1.35,.24,.13,SELECT);
      m.ring(x,z,1.63,.10,.13,SELECT);
    }
  }
  if(p.ball){
    const world=safeField(p.ball.x,p.ball.y,0);
    // Ball height is NOT available in these inputs. Render at ground level.
    if(world)m.cylinder(world[0],world[2],.28,.22,.18,[.77,.52,.26]);
  }
  return new Float32Array(m.values);
}
function compile(gl:WebGL2RenderingContext, type:number, source:string):WebGLShader {
  const shader=gl.createShader(type);
  if(!shader)throw new Error('Shader allocation failed');
  gl.shaderSource(shader,source);
  gl.compileShader(shader);
  if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS)){
    const error=gl.getShaderInfoLog(shader)||'Shader compile failed';
    gl.deleteShader(shader);throw new Error(error);
  }
  return shader;
}
class Renderer {
  gl:WebGL2RenderingContext;
  program:WebGLProgram;
  turf:WebGLBuffer;
  actors:WebGLBuffer;
  turfCount:number;
  attribPosition:number;
  attribColor:number;
  eye:WebGLUniformLocation|null;
  right:WebGLUniformLocation|null;
  up:WebGLUniformLocation|null;
  forward:WebGLUniformLocation|null;
  lens:WebGLUniformLocation|null;
  constructor(gl:WebGL2RenderingContext) {
    this.gl=gl;
    const v=compile(gl,gl.VERTEX_SHADER,VERTEX),f=compile(gl,gl.FRAGMENT_SHADER,FRAGMENT);
    const program=gl.createProgram();
    if(!program)throw new Error('WebGL program allocation failed');
    gl.attachShader(program,v);gl.attachShader(program,f);
    gl.linkProgram(program);
    gl.deleteShader(v);gl.deleteShader(f);
    if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(program)||'Program link failed');
    this.program=program;
    const turf=gl.createBuffer(),actors=gl.createBuffer();
    if(!turf||!actors)throw new Error('WebGL buffer allocation failed');
    this.turf=turf;this.actors=actors;
    this.attribPosition=gl.getAttribLocation(program,'a_position');
    this.attribColor=gl.getAttribLocation(program,'a_color');
    this.eye=gl.getUniformLocation(program,'u_eye');
    this.right=gl.getUniformLocation(program,'u_right');
    this.up=gl.getUniformLocation(program,'u_up');
    this.forward=gl.getUniformLocation(program,'u_forward');
    this.lens=gl.getUniformLocation(program,'u_lens');
    const geometry=buildTurf();
    gl.bindBuffer(gl.ARRAY_BUFFER,this.turf);
    gl.bufferData(gl.ARRAY_BUFFER,geometry,gl.STATIC_DRAW);
    this.turfCount=geometry.length/6;
    gl.enable(gl.DEPTH_TEST);
    gl.depthFunc(gl.LEQUAL);
  }
  private bind(buffer:WebGLBuffer){
    const gl=this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
    gl.vertexAttribPointer(this.attribPosition,3,gl.FLOAT,false,24,0);
    gl.vertexAttribPointer(this.attribColor,3,gl.FLOAT,false,24,12);
    gl.enableVertexAttribArray(this.attribPosition);
    gl.enableVertexAttribArray(this.attribColor);
  }
  draw(orbit:Orbit,props:Props,canvas:HTMLCanvasElement,overlay:HTMLCanvasElement){
    const gl=this.gl;
    const w=canvas.clientWidth,h=canvas.clientHeight;
    if(!w||!h)return;
    const dpr=Math.min(1.6,Math.max(1,window.devicePixelRatio||1));
    const bw=Math.round(w*dpr),bh=Math.round(h*dpr);
    if(canvas.width!==bw||canvas.height!==bh){canvas.width=bw;canvas.height=bh;}
    if(overlay.width!==bw||overlay.height!==bh){overlay.width=bw;overlay.height=bh;}
    const camera=orbitCamera(orbit,w/h);
    gl.viewport(0,0,bw,bh);
    gl.clearColor(.035,.07,.11,1);
    gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
    gl.useProgram(this.program);
    gl.uniform3fv(this.eye,new Float32Array(camera.eye));
    gl.uniform3fv(this.right,new Float32Array(camera.right));
    gl.uniform3fv(this.up,new Float32Array(camera.up));
    gl.uniform3fv(this.forward,new Float32Array(camera.forward));
    gl.uniform4fv(this.lens,lensUniforms(camera));
    this.bind(this.turf);
    gl.drawArrays(gl.TRIANGLES,0,this.turfCount);
    const dynamic=buildActors(props);
    this.bind(this.actors);
    gl.bufferData(gl.ARRAY_BUFFER,dynamic,gl.DYNAMIC_DRAW);
    gl.drawArrays(gl.TRIANGLES,0,dynamic.length/6);
    drawTextLabels(overlay,camera,props,w,h,dpr);
  }
  dispose(){
    const gl=this.gl;
    gl.deleteBuffer(this.turf);
    gl.deleteBuffer(this.actors);
    gl.deleteProgram(this.program);
  }
}
function drawTextLabels(
  canvas:HTMLCanvasElement,camera:CameraBasis,props:Props,width:number,height:number,dpr:number
){
  const ctx=canvas.getContext('2d');if(!ctx)return;
  ctx.clearRect(0,0,canvas.width,canvas.height);
  ctx.save();ctx.scale(dpr,dpr);
  ctx.textAlign='center';ctx.font='700 11px ui-sans-serif, system-ui';
  for(let yard=10;yard<=110;yard+=10){
    const x=yard-60,number=yard<=60?yard-10:110-yard;
    for(const z of [-21.4,21.4]){
      const p=projectToScreen([x,.11,z],camera,width,height);
      if(!p.visible)continue;
      ctx.fillStyle='rgba(227,255,236,.64)';
      ctx.fillText(String(number),p.x,p.y);
    }
  }
  if(props.showLabels!==false){
    for(const p of props.players){
      const at=safeField(p.x,p.y,2.75);
      if(!at)continue;
      const screen=projectToScreen(at,camera,width,height);
      if(!screen.visible)continue;
      const label=(p.jersey||p.name||p.id).slice(0,17);
      ctx.font=p.id===props.selectedId?'bold 13px ui-sans-serif, system-ui':'600 11px ui-sans-serif, system-ui';
      const tw=ctx.measureText(label).width;
      ctx.fillStyle='rgba(9,23,33,.86)';ctx.fillRect(screen.x-tw/2-5,screen.y-13,tw+10,18);
      ctx.fillStyle=p.id===props.selectedId?'#ffdf98':'#e5f0f7';
      ctx.fillText(label,screen.x,screen.y);
    }
  }
  ctx.restore();
}
export function FootballField3D(props:Props) {
  const canvasRef=useRef<HTMLCanvasElement>(null);
  const labelsRef=useRef<HTMLCanvasElement>(null);
  const rendererRef=useRef<Renderer|null>(null);
  const propsRef=useRef(props);propsRef.current=props;
  const [orbit,setOrbit]=useState<Orbit>(()=>defaultOrbit(props.preset,props.focus));
  const orbitRef=useRef(orbit);orbitRef.current=orbit;
  const [error,setError]=useState<string|null>(null);
  const drag=useRef<{x:number;y:number;button:number;moved:boolean}|null>(null);
  const draw=useCallback(()=>{
    const renderer=rendererRef.current,canvas=canvasRef.current,overlay=labelsRef.current;
    if(renderer&&canvas&&overlay)renderer.draw(orbitRef.current,propsRef.current,canvas,overlay);
  },[]);
  useEffect(()=>{setOrbit(defaultOrbit(props.preset,props.focus));},[props.preset,props.focus]);
  useEffect(()=>{draw();},[draw,orbit,props.players,props.ball,props.trails,props.selectedId,props.showTrails,props.showLabels,props.showNearest,props.snapPlayers,props.showSnap]);
  useEffect(()=>{
    const canvas=canvasRef.current;
    if(!canvas)return;
    let active=true;
    try{
      const gl=canvas.getContext('webgl2',{antialias:true,alpha:false,powerPreference:'low-power'});
      if(!gl)throw new Error('WebGL2 is unavailable in this browser');
      rendererRef.current=new Renderer(gl);
      draw();
    }catch(e){setError(e instanceof Error?e.message:'Unable to initialize WebGL2');propsRef.current.onUnsupported?.();}
    const resize=new ResizeObserver(()=>{if(active)draw();});
    resize.observe(canvas);
    const lost=(e:Event)=>{e.preventDefault();setError('3D graphics context lost. Switch to the 2D field.');propsRef.current.onUnsupported?.();};
    canvas.addEventListener('webglcontextlost',lost);
    return ()=>{
      active=false;
      resize.disconnect();
      canvas.removeEventListener('webglcontextlost',lost);
      rendererRef.current?.dispose();rendererRef.current=null;
    };
  },[draw]);
  const selectAt=(x:number,y:number)=>{
    const canvas=canvasRef.current;if(!canvas)return;
    const cam=orbitCamera(orbitRef.current,canvas.clientWidth/canvas.clientHeight);
    const near=propsRef.current.players.map(p=>{
      const at=safeField(p.x,p.y,1.5);
      const sc=at?projectToScreen(at,cam,canvas.clientWidth,canvas.clientHeight):null;
      return {p,d:sc&&sc.visible?Math.hypot(sc.x-x,sc.y-y):Infinity};
    }).sort((a,b)=>a.d-b.d)[0];
    if(near&&near.d<22)propsRef.current.onSelect(near.p.id);
  };
  const onPointerDown=(e:React.PointerEvent<HTMLCanvasElement>)=>{
    if(e.button!==0&&e.button!==2)return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current={x:e.clientX,y:e.clientY,button:e.button,moved:false};
  };
  const onPointerMove=(e:React.PointerEvent<HTMLCanvasElement>)=>{
    const active=drag.current;if(!active)return;
    const dx=e.clientX-active.x,dy=e.clientY-active.y;
    if(Math.hypot(dx,dy)>2)active.moved=true;
    active.x=e.clientX;active.y=e.clientY;
    if(active.button===2||e.shiftKey){
      setOrbit(old=>({...old,target:[
        clamp(old.target[0]-dx*.18,-52,52),0,clamp(old.target[2]+dy*.18,-22,22),
      ]}));
    }else{
      setOrbit(old=>({...old,azimuth:old.azimuth-dx*.008,
        elevation:clamp(old.elevation+dy*.006,.16,1.53)}));
    }
  };
  const onPointerUp=(e:React.PointerEvent<HTMLCanvasElement>)=>{
    const active=drag.current;drag.current=null;
    if(!active||active.moved||active.button!==0)return;
    const rect=e.currentTarget.getBoundingClientRect();
    selectAt(e.clientX-rect.left,e.clientY-rect.top);
  };
  useEffect(()=>{
    const canvas=canvasRef.current;if(!canvas)return;
    const onWheel=(e:WheelEvent)=>{
      e.preventDefault();
      setOrbit(old=>({...old,distance:clamp(old.distance*Math.exp(e.deltaY*.0011),40,260)}));
    };
    canvas.addEventListener('wheel',onWheel,{passive:false});
    return ()=>canvas.removeEventListener('wheel',onWheel);
  },[]);
  return <div className="field3d-shell">
    <div className="field3d-stage">
      <canvas ref={canvasRef} aria-label="3D interactive football field: drag to orbit, shift-drag to pan, wheel to zoom; use the player list to select with keyboard" onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onContextMenu={e=>e.preventDefault()} />
      <canvas ref={labelsRef} aria-hidden="true" className="field3d-labels" />
      <div className="field3d-source"><Scan size={14}/> {props.synthetic?'ILLUSTRATIVE MOVEMENT':'RECORDED X/Y · 3D FIELD'} · BALL HEIGHT UNKNOWN</div>
      {error&&<div className="field3d-unavailable" role="alert">{error}<p>Choose 2D field to continue inspecting the replay.</p></div>}
      <div className="field3d-legend" aria-hidden="true"><span><i className="field3d-offense"/>Offense</span><span><i className="field3d-defense"/>Defense</span><span><i className="field3d-unknown"/>Unknown</span></div>
    </div>
    <div className="field3d-controls">
      <span>Drag: orbit · Shift/right-drag: pan · Scroll: zoom · Click: inspect</span>
      <div>
        <button type="button" aria-label="Zoom in on field" onClick={()=>setOrbit(o=>({...o,distance:clamp(o.distance*.78,40,260)}))}><ZoomIn size={16}/></button>
        <button type="button" aria-label="Zoom out from field" onClick={()=>setOrbit(o=>({...o,distance:clamp(o.distance*1.24,40,260)}))}><ZoomOut size={16}/></button>
        <button type="button" aria-label="Reset field camera" onClick={()=>setOrbit(defaultOrbit(props.preset,props.focus))}><RotateCcw size={16}/></button>
      </div>
    </div>
  </div>;
}
