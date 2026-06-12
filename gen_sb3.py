#!/usr/bin/env python3
"""Génère un casse-briques Scratch 3.0 (.sb3) avec PV par rangée."""
import json, zipfile, uuid, hashlib

def uid(): return uuid.uuid4().hex[:20]
def md5hex(d): return hashlib.md5(d if isinstance(d,bytes) else d.encode()).hexdigest()

# ── IDs globaux ──────────────────────────────────────────────────────────────
V = {k:uid() for k in ['score','vies','bvx','bvy','rangee','col','mon_id','mon_pv']}
L = {'bpv':uid(),'bmax':uid()}
BR = {'frappe':uid(),'perdu':uid()}

ROWS=6; COLS=8; BW=48; BH=16; GAP=4
BDX=BW+GAP; BDY=BH+GAP   # 52, 20
BX0=-182; BY0=150          # centre col0, centre row0

ROW_HP     = [6,5,4,3,2,1]
ROW_COLORS = ['#e74c3c','#e67e22','#f1c40f','#2ecc71','#3498db','#9b59b6']

# ── Constructeur de blocs ────────────────────────────────────────────────────
class SB:
    def __init__(self): self.blks={}
    def b(self,op,nxt=None,par=None,inp=None,fld=None,sh=False,tl=False,x=0,y=0):
        bid=uid()
        bl={'opcode':op,'next':nxt,'parent':par,'inputs':inp or {},'fields':fld or {},'shadow':sh,'topLevel':tl}
        if tl: bl['x']=x; bl['y']=y
        self.blks[bid]=bl; return bid
    def lnk(self,a,b):
        if a and b: self.blks[a]['next']=b; self.blks[b]['parent']=a
    def sq(self,*ids):
        for i in range(len(ids)-1): self.lnk(ids[i],ids[i+1])
        return ids[0] if ids else None
    def sub(self,c,inner,sl='SUBSTACK'):
        if inner: self.blks[c]['inputs'][sl]=[2,inner]; self.blks[inner]['parent']=c
    # valeurs
    def N(self,v): return [1,[4,str(v)]]
    def S(self,v): return [1,[10,str(v)]]
    def vr(self,n,vid):
        bid=self.b('data_variable',fld={'VARIABLE':[n,vid]}); return [3,bid,[4,'0']]
    def nr(self,bid): return [3,bid,[4,'0']]
    def cn(self,bid): return [2,bid]
    # reporters arithmétiques
    def add(self,a,b): return self.b('operator_add',inp={'NUM1':a,'NUM2':b})
    def sub_(self,a,b): return self.b('operator_subtract',inp={'NUM1':a,'NUM2':b})
    def mul(self,a,b): return self.b('operator_multiply',inp={'NUM1':a,'NUM2':b})
    def div(self,a,b): return self.b('operator_divide',inp={'NUM1':a,'NUM2':b})
    def absv(self,a): return self.b('operator_mathop',inp={'NUM':a},fld={'OPERATOR':['abs',None]})
    def floorv(self,a): return self.b('operator_mathop',inp={'NUM':a},fld={'OPERATOR':['floor',None]})
    def gt(self,a,b): return self.b('operator_gt',inp={'OPERAND1':a,'OPERAND2':b})
    def lt(self,a,b): return self.b('operator_lt',inp={'OPERAND1':a,'OPERAND2':b})
    def eq(self,a,b): return self.b('operator_equals',inp={'OPERAND1':a,'OPERAND2':b})
    def and_(self,a,b): return self.b('operator_and',inp={'OPERAND1':a,'OPERAND2':b})
    def rand(self,a,b): return self.b('operator_random',inp={'FROM':a,'TO':b})
    def xpos(self): return self.b('motion_xposition')
    def ypos(self): return self.b('motion_yposition')
    def mousex(self): return self.b('sensing_mousex')
    def touching(self,name):
        m=self.b('sensing_touchingobjectmenu',sh=True,fld={'TOUCHINGOBJECTMENU':[name,None]})
        return self.b('sensing_touchingobject',inp={'TOUCHINGOBJECTMENU':[1,m]})
    def li(self,ln,lid,idx): return self.b('data_itemoflist',inp={'INDEX':idx},fld={'LIST':[ln,lid]})
    def of_(self,prop,obj):
        m=self.b('sensing_of_object_menu',sh=True,fld={'OBJECT':[obj,None]})
        return self.b('sensing_of',inp={'OBJECT':[1,m]},fld={'PROPERTY':[prop,None]})
    # instructions
    def flag(self,x=20,y=20): return self.b('event_whenflagclicked',tl=True,x=x,y=y)
    def cs(self,x=20,y=20): return self.b('event_whenIstartasaclone',tl=True,x=x,y=y)
    def recv(self,name,mid,x=20,y=20):
        return self.b('event_whenbroadcastreceived',tl=True,x=x,y=y,fld={'BROADCAST_OPTION':[name,mid]})
    def bcast(self,name,mid):
        m=self.b('event_broadcast_menu',sh=True,fld={'BROADCAST_OPTION':[name,mid]})
        return self.b('event_broadcast',inp={'BROADCAST_INPUT':[1,m]})
    def bcast_w(self,name,mid):
        m=self.b('event_broadcast_menu',sh=True,fld={'BROADCAST_OPTION':[name,mid]})
        return self.b('event_broadcastandwait',inp={'BROADCAST_INPUT':[1,m]})
    def goto(self,x,y): return self.b('motion_gotoxy',inp={'X':x,'Y':y})
    def setx(self,x): return self.b('motion_setx',inp={'X':x})
    def sety(self,y): return self.b('motion_sety',inp={'Y':y})
    def chx(self,dx): return self.b('motion_changexby',inp={'DX':dx})
    def chy(self,dy): return self.b('motion_changeyby',inp={'DY':dy})
    def show(self): return self.b('looks_show')
    def hide(self): return self.b('looks_hide')
    def costume_v(self,val): return self.b('looks_switchcostumeto',inp={'COSTUME':val})
    def effect(self,eff,val): return self.b('looks_seteffectto',inp={'VALUE':val},fld={'EFFECT':[eff,None]})
    def clr_eff(self): return self.b('looks_cleargraphiceffects')
    def say_s(self,msg,dur): return self.b('looks_sayforsecs',inp={'MESSAGE':self.S(msg),'SECS':self.N(dur)})
    def setv(self,n,vid,val): return self.b('data_setvariableto',inp={'VALUE':val},fld={'VARIABLE':[n,vid]})
    def chv(self,n,vid,val): return self.b('data_changevariableby',inp={'VALUE':val},fld={'VARIABLE':[n,vid]})
    def add_l(self,ln,lid,item): return self.b('data_addtolist',inp={'ITEM':item},fld={'LIST':[ln,lid]})
    def del_l(self,ln,lid): return self.b('data_deletealloflist',fld={'LIST':[ln,lid]})
    def rep_l(self,ln,lid,idx,item):
        return self.b('data_replaceitemoflist',inp={'INDEX':idx,'ITEM':item},fld={'LIST':[ln,lid]})
    def wait(self,dur): return self.b('control_wait',inp={'DURATION':dur})
    def forever(self): return self.b('control_forever')
    def repeat(self,t): return self.b('control_repeat',inp={'TIMES':t})
    def if_(self,c): return self.b('control_if',inp={'CONDITION':c})
    def ife(self,c): return self.b('control_if_else',inp={'CONDITION':c})
    def clone(self):
        m=self.b('control_create_clone_of_menu',sh=True,fld={'CLONE_OPTION':['_myself_',None]})
        return self.b('control_create_clone_of',inp={'CLONE_OPTION':[1,m]})
    def del_c(self): return self.b('control_delete_this_clone')
    def stop(self,opt='all'): return self.b('control_stop',fld={'STOP_OPTION':[opt,None]})

# ── BALLE ────────────────────────────────────────────────────────────────────
def build_ball():
    s=SB()
    f=s.flag(x=20,y=20)
    i0=s.setv('score',V['score'],s.N(0))
    i1=s.setv('vies',V['vies'],s.N(3))
    i2=s.goto(s.N(0),s.N(-100))
    i3=s.setv('bvx',V['bvx'],s.nr(s.rand(s.N(-4),s.N(4))))
    i4=s.setv('bvy',V['bvy'],s.N(5))
    i5=s.clr_eff(); i6=s.show(); fv=s.forever()
    s.sq(f,i0,i1,i2,i3,i4,i5,i6,fv)

    # Corps de la boucle forever
    m1=s.chx(s.vr('bvx',V['bvx']))
    m2=s.chy(s.vr('bvy',V['bvy']))

    # Mur droit
    c1=s.gt(s.nr(s.xpos()),s.N(222))
    t1=s.setv('bvx',V['bvx'],s.nr(s.sub_(s.N(0),s.nr(s.absv(s.vr('bvx',V['bvx']))))))
    w1=s.setx(s.N(220)); s.sq(t1,w1)
    f1=s.if_(s.cn(c1)); s.sub(f1,t1)

    # Mur gauche
    c2=s.lt(s.nr(s.xpos()),s.N(-222))
    t2=s.setv('bvx',V['bvx'],s.nr(s.absv(s.vr('bvx',V['bvx']))))
    w2=s.setx(s.N(-220)); s.sq(t2,w2)
    f2=s.if_(s.cn(c2)); s.sub(f2,t2)

    # Plafond
    c3=s.gt(s.nr(s.ypos()),s.N(162))
    t3=s.setv('bvy',V['bvy'],s.nr(s.sub_(s.N(0),s.nr(s.absv(s.vr('bvy',V['bvy']))))))
    f3=s.if_(s.cn(c3)); s.sub(f3,t3)

    # Raquette
    t_raq=s.touching('Raquette')
    bvy_neg=s.lt(s.vr('bvy',V['bvy']),s.N(0))
    c4=s.and_(s.cn(t_raq),s.cn(bvy_neg))
    padx=s.of_('x position','Raquette')
    diff=s.sub_(s.nr(s.xpos()),s.nr(padx))
    new_bvx=s.div(s.nr(diff),s.N(10))
    p1=s.setv('bvx',V['bvx'],s.nr(new_bvx))
    p2=s.setv('bvy',V['bvy'],s.nr(s.absv(s.vr('bvy',V['bvy']))))
    p3=s.sety(s.N(-148)); s.sq(p1,p2,p3)
    f4=s.if_(s.cn(c4)); s.sub(f4,p1)

    # Brique
    t_br=s.touching('Brique')
    b1=s.setv('bvy',V['bvy'],s.nr(s.sub_(s.N(0),s.vr('bvy',V['bvy']))))
    b2=s.bcast_w('frappe',BR['frappe']); s.sq(b1,b2)
    f5=s.if_(s.cn(t_br)); s.sub(f5,b1)

    # Balle perdue
    c5=s.lt(s.nr(s.ypos()),s.N(-170))
    l1=s.chv('vies',V['vies'],s.N(-1))
    c_go=s.eq(s.vr('vies',V['vies']),s.N(0))
    go1=s.bcast('perdu',BR['perdu']); go2=s.stop(); s.sq(go1,go2)
    if_go=s.if_(s.cn(c_go)); s.sub(if_go,go1)
    r1=s.goto(s.N(0),s.N(-100))
    r2=s.setv('bvx',V['bvx'],s.nr(s.rand(s.N(-4),s.N(4))))
    r3=s.setv('bvy',V['bvy'],s.N(5))
    r4=s.wait(s.N(1))
    s.sq(l1,if_go,r1,r2,r3,r4)
    f6=s.if_(s.cn(c5)); s.sub(f6,l1)

    s.sq(m1,m2,f1,f2,f3,f4,f5,f6)
    s.sub(fv,m1)

    # Game over message
    rp=s.recv('perdu',BR['perdu'],x=300,y=20)
    sg=s.say_s('GAME OVER !',3); s.sq(rp,sg)
    return s.blks

# ── RAQUETTE ─────────────────────────────────────────────────────────────────
def build_paddle():
    s=SB()
    f=s.flag(x=20,y=20); sh=s.show(); fv=s.forever()
    s.sq(f,sh,fv)
    mx=s.mousex()
    g=s.goto(s.nr(mx),s.N(-155))
    c1=s.gt(s.nr(s.xpos()),s.N(195)); t1=s.setx(s.N(195))
    f1=s.if_(s.cn(c1)); s.sub(f1,t1)
    c2=s.lt(s.nr(s.xpos()),s.N(-195)); t2=s.setx(s.N(-195))
    f2=s.if_(s.cn(c2)); s.sub(f2,t2)
    s.sq(g,f1,f2); s.sub(fv,g)
    return s.blks

# ── BRIQUES ──────────────────────────────────────────────────────────────────
def build_brick():
    s=SB()

    # Script 1 : Initialisation (drapeau vert)
    f=s.flag(x=20,y=20)
    d1=s.del_l('bpv',L['bpv']); d2=s.del_l('bmax',L['bmax'])
    hm=s.hide()

    # Remplir les listes bpv et bmax
    sr=s.setv('rangee',V['rangee'],s.N(0)); rr=s.repeat(s.N(ROWS))
    sc=s.setv('col',V['col'],s.N(0)); rc=s.repeat(s.N(COLS))
    hp1=s.sub_(s.N(6),s.vr('rangee',V['rangee']))
    a1=s.add_l('bpv',L['bpv'],s.nr(hp1))
    hp2=s.sub_(s.N(6),s.vr('rangee',V['rangee']))
    a2=s.add_l('bmax',L['bmax'],s.nr(hp2))
    cc1=s.chv('col',V['col'],s.N(1))
    s.sq(a1,a2,cc1); s.sub(rc,a1)
    cr1=s.chv('rangee',V['rangee'],s.N(1))
    s.sq(sc,rc,cr1); s.sub(rr,sc)

    # Créer les clones aux bonnes positions
    sr2=s.setv('rangee',V['rangee'],s.N(0)); rr2=s.repeat(s.N(ROWS))
    sc2=s.setv('col',V['col'],s.N(0)); rc2=s.repeat(s.N(COLS))
    tx=s.add(s.N(BX0),s.nr(s.mul(s.vr('col',V['col']),s.N(BDX))))
    ty=s.sub_(s.N(BY0),s.nr(s.mul(s.vr('rangee',V['rangee']),s.N(BDY))))
    g1=s.goto(s.nr(tx),s.nr(ty))
    cos=s.add(s.vr('rangee',V['rangee']),s.N(1))
    csw=s.costume_v(s.nr(cos))
    sh2=s.show(); cl=s.clone(); hd2=s.hide()
    cc2=s.chv('col',V['col'],s.N(1))
    s.sq(g1,csw,sh2,cl,hd2,cc2); s.sub(rc2,g1)
    cr2=s.chv('rangee',V['rangee'],s.N(1))
    s.sq(sc2,rc2,cr2); s.sub(rr2,sc2)

    s.sq(f,d1,d2,hm,sr,rr,sr2,rr2)

    # Script 2 : démarrage clone
    cs=s.cs(x=400,y=20); sh3=s.show(); s.sq(cs,sh3)

    # Script 3 : réception 'frappe'
    rv=s.recv('frappe',BR['frappe'],x=700,y=20)
    t_ball=s.touching('Balle')

    # Calcul index depuis position
    yp=s.ypos()
    y_diff=s.sub_(s.N(BY0),s.nr(yp))
    row_f=s.div(s.nr(y_diff),s.N(BDY))
    row_r=s.floorv(s.nr(row_f))
    xp=s.xpos()
    x_diff=s.sub_(s.nr(xp),s.N(BX0))
    col_f=s.div(s.nr(x_diff),s.N(BDX))
    col_r=s.floorv(s.nr(col_f))
    rp=s.mul(s.nr(row_r),s.N(COLS))
    idx=s.add(s.nr(rp),s.nr(col_r))
    idx1=s.add(s.nr(idx),s.N(1))
    set_id=s.setv('mon_id',V['mon_id'],s.nr(idx1))

    # Lire PV actuel
    cur_hp=s.li('bpv',L['bpv'],s.vr('mon_id',V['mon_id']))
    set_pv=s.setv('mon_pv',V['mon_pv'],s.nr(cur_hp))

    # Décrémenter
    new_hp=s.sub_(s.vr('mon_pv',V['mon_pv']),s.N(1))
    rep_hp=s.rep_l('bpv',L['bpv'],s.vr('mon_id',V['mon_id']),s.nr(new_hp))

    # Score
    ch_sc=s.chv('score',V['score'],s.N(10))

    # Effet visuel (brightness selon dégâts)
    max_hp=s.li('bmax',L['bmax'],s.vr('mon_id',V['mon_id']))
    cur_aft=s.sub_(s.vr('mon_pv',V['mon_pv']),s.N(1))
    ratio=s.div(s.nr(cur_aft),s.nr(max_hp))
    bright=s.mul(s.nr(s.sub_(s.N(1),s.nr(ratio))),s.N(80))
    set_br=s.effect('brightness',s.nr(bright))

    # Mort ?
    c_dead=s.eq(s.vr('mon_pv',V['mon_pv']),s.N(1))
    dc=s.del_c()
    if_dead=s.if_(s.cn(c_dead)); s.sub(if_dead,dc)

    s.sq(set_id,set_pv,rep_hp,ch_sc,set_br,if_dead)
    if_touch=s.if_(s.cn(t_ball)); s.sub(if_touch,set_id)
    s.sq(rv,if_touch)

    return s.blks

# ── SVG Costumes ─────────────────────────────────────────────────────────────
def ball_svg():
    return b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><circle cx="8" cy="8" r="8" fill="white"/><circle cx="5" cy="5" r="3" fill="rgba(255,255,255,0.4)"/></svg>'

def paddle_svg():
    return b'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="14"><rect width="80" height="14" rx="7" fill="#7ee8fa"/><rect x="4" y="3" width="72" height="5" rx="2" fill="rgba(255,255,255,0.4)"/></svg>'

def brick_svg(color):
    r,g,b2=int(color[1:3],16),int(color[3:5],16),int(color[5:7],16)
    lr,lg,lb=min(255,r+60),min(255,g+60),min(255,b2+60)
    lighter=f'#{lr:02x}{lg:02x}{lb:02x}'
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="48" height="16"><rect width="48" height="16" rx="3" fill="{color}"/><rect x="2" y="2" width="44" height="7" rx="2" fill="{lighter}" opacity="0.35"/></svg>'.encode()

def backdrop_svg():
    return b'<svg xmlns="http://www.w3.org/2000/svg" width="480" height="360"><rect width="480" height="360" fill="#1a1a2e"/><text x="240" y="340" text-anchor="middle" font-family="sans-serif" font-size="12" fill="rgba(100,100,200,0.5)">Casse-Briques Ultra</text></svg>'

def mk_costume(name,data,cx,cy):
    aid=md5hex(data)
    return {'name':name,'bitmapResolution':1,'dataFormat':'svg','assetId':aid,'md5ext':f'{aid}.svg','rotationCenterX':cx,'rotationCenterY':cy},aid,data

# ── Assemblage projet ─────────────────────────────────────────────────────────
def build():
    assets={}

    bd=backdrop_svg(); bdid=md5hex(bd); assets[bdid]=(f'{bdid}.svg',bd)
    bal=ball_svg(); balc,balid,_=mk_costume('balle',bal,8,8); assets[balid]=(f'{balid}.svg',bal)
    pad=paddle_svg(); padc,padid,_=mk_costume('raquette',pad,40,7); assets[padid]=(f'{padid}.svg',pad)

    bk_costumes=[]
    for i,c in enumerate(ROW_COLORS):
        sv=brick_svg(c); bc2,bid2,_=mk_costume(f'brique_{i+1}',sv,24,8)
        bk_costumes.append(bc2); assets[bid2]=(f'{bid2}.svg',sv)

    stage={
        'isStage':True,'name':'Stage',
        'variables':{vid:[n,0] for n,vid in V.items()},
        'lists':{lid:[n,[]] for n,lid in L.items()},
        'broadcasts':{bid:n for n,bid in BR.items()},
        'blocks':{},'comments':{},'currentCostume':0,
        'costumes':[{'name':'fond','bitmapResolution':1,'dataFormat':'svg','assetId':bdid,'md5ext':f'{bdid}.svg','rotationCenterX':240,'rotationCenterY':180}],
        'sounds':[],'volume':100,'layerOrder':0,'tempo':60,'videoTransparency':50,'videoState':'on','textToSpeechLanguage':None
    }

    ball_sp={
        'isStage':False,'name':'Balle','variables':{},'lists':{},'broadcasts':{},
        'blocks':build_ball(),'comments':{},'currentCostume':0,
        'costumes':[balc],'sounds':[],'volume':100,'layerOrder':3,
        'visible':True,'x':0,'y':-100,'size':100,'direction':90,'draggable':False,'rotationStyle':'all around'
    }

    pad_sp={
        'isStage':False,'name':'Raquette','variables':{},'lists':{},'broadcasts':{},
        'blocks':build_paddle(),'comments':{},'currentCostume':0,
        'costumes':[padc],'sounds':[],'volume':100,'layerOrder':2,
        'visible':True,'x':0,'y':-155,'size':100,'direction':90,'draggable':False,"rotationStyle":"don't rotate"
    }

    bk_sp={
        'isStage':False,'name':'Brique','variables':{},'lists':{},'broadcasts':{},
        'blocks':build_brick(),'comments':{},'currentCostume':0,
        'costumes':bk_costumes,'sounds':[],'volume':100,'layerOrder':1,
        'visible':True,'x':0,'y':0,'size':100,'direction':90,'draggable':False,"rotationStyle":"don't rotate"
    }

    monitors=[
        {'id':V['score'],'mode':'default','opcode':'data_variable','params':{'VARIABLE':'score'},'spriteName':None,'value':0,'width':0,'height':0,'x':5,'y':5,'visible':True,'sliderMin':0,'sliderMax':100,'isDiscrete':True},
        {'id':V['vies'],'mode':'default','opcode':'data_variable','params':{'VARIABLE':'vies'},'spriteName':None,'value':3,'width':0,'height':0,'x':5,'y':30,'visible':True,'sliderMin':0,'sliderMax':100,'isDiscrete':True},
    ]

    project={
        'targets':[stage,ball_sp,pad_sp,bk_sp],
        'monitors':monitors,'extensions':[],
        'meta':{'semver':'3.0.0','vm':'0.2.0','agent':'CasseBriquesGen'}
    }
    return project,assets

def main():
    project,assets=build()
    pjson=json.dumps(project,ensure_ascii=False).encode('utf-8')
    out=r'c:\Users\tsumu\Documents\projet_test\casse_briques.sb3'
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('project.json',pjson)
        for _,(fname,data) in assets.items():
            zf.writestr(fname,data)
    print(f'✓ Fichier généré : {out}')
    print(f'  Sprites : Balle, Raquette, Brique')
    print(f'  Rangées : {ROWS}  |  Colonnes : {COLS}')
    print(f'  PV par rangée (haut→bas) : {ROW_HP}')

if __name__=='__main__':
    main()
