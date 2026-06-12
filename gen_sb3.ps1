Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$tmp = Join-Path $env:TEMP 'sb3gen3'
if (Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp | Out-Null

function uid { [System.Guid]::NewGuid().ToString('N').Substring(0,20) }
function md5b([byte[]]$b){ $m=[System.Security.Cryptography.MD5]::Create(); ($m.ComputeHash($b)|ForEach-Object{$_.ToString('x2')}) -join '' }
function utf8($s){ [System.Text.Encoding]::UTF8.GetBytes([string]$s) }
function wf($name,[byte[]]$data){ [System.IO.File]::WriteAllBytes("$tmp\$name",$data) }

$ROWS=6;$COLS=8;$BX0=-182;$BY0=150;$BDX=52;$BDY=20
$RC  =@('#e74c3c','#e67e22','#f1c40f','#2ecc71','#3498db','#9b59b6')
$RCL =@('#ff8080','#ffb366','#ffe766','#7fffa9','#7fc8ff','#c47fd9')  # lighter versions

$Vs=@{};foreach($k in @('score','vies','bvx','bvy','rangee','col','mon_id','mon_pv','speed_factor','pad_large','pu_x','pu_y','pu_type')){$Vs[$k]=uid}
$Ls=@{bpv=uid;bmax=uid}
$BRs=@{frappe=uid;perdu=uid;spawn_pu=uid}

function NewDict { New-Object 'System.Collections.Generic.Dictionary[string,object]' }

function Bk([ref]$d,$op,$nxt,$par,$inp,$fld,[bool]$sh=$false,[bool]$tl=$false,[int]$x=0,[int]$y=0){
    $bid=uid
    $bl=@{opcode=$op;next=$nxt;parent=$par;inputs=if($inp){$inp}else{@{}};fields=if($fld){$fld}else{@{}};shadow=$sh;topLevel=$tl}
    if($tl){$bl['x']=$x;$bl['y']=$y}
    $d.Value[$bid]=$bl;return $bid
}
function Lk([ref]$d,$a,$b){ if($a-and$b){$d.Value[$a]['next']=$b;$d.Value[$b]['parent']=$a} }
function At([ref]$d,$c,$inner,$sl='SUBSTACK'){ if($inner){$d.Value[$c]['inputs'][$sl]=@(2,$inner);$d.Value[$inner]['parent']=$c} }

function N($v){ @(1,@(4,"$v")) }
function VR([ref]$d,$n,$vid){ $bid=Bk $d 'data_variable' $null $null $null @{VARIABLE=@($n,$vid)}; @(3,$bid,@(4,'0')) }
function NR($bid){ @(3,$bid,@(4,'0')) }
function CN($bid){ @(2,$bid) }

function rAdd([ref]$d,$a,$b){ Bk $d 'operator_add' $null $null @{NUM1=$a;NUM2=$b} $null }
function rSub([ref]$d,$a,$b){ Bk $d 'operator_subtract' $null $null @{NUM1=$a;NUM2=$b} $null }
function rMul([ref]$d,$a,$b){ Bk $d 'operator_multiply' $null $null @{NUM1=$a;NUM2=$b} $null }
function rDiv([ref]$d,$a,$b){ Bk $d 'operator_divide' $null $null @{NUM1=$a;NUM2=$b} $null }
function rAbs([ref]$d,$a){ Bk $d 'operator_mathop' $null $null @{NUM=$a} @{OPERATOR=@('abs',$null)} }
function rFloor([ref]$d,$a){ Bk $d 'operator_mathop' $null $null @{NUM=$a} @{OPERATOR=@('floor',$null)} }
function rGt([ref]$d,$a,$b){ Bk $d 'operator_gt' $null $null @{OPERAND1=$a;OPERAND2=$b} $null }
function rLt([ref]$d,$a,$b){ Bk $d 'operator_lt' $null $null @{OPERAND1=$a;OPERAND2=$b} $null }
function rEq([ref]$d,$a,$b){ Bk $d 'operator_equals' $null $null @{OPERAND1=$a;OPERAND2=$b} $null }
function rAnd([ref]$d,$a,$b){ Bk $d 'operator_and' $null $null @{OPERAND1=$a;OPERAND2=$b} $null }
function rOr([ref]$d,$a,$b){ Bk $d 'operator_or' $null $null @{OPERAND1=$a;OPERAND2=$b} $null }
function rRand([ref]$d,$a,$b){ Bk $d 'operator_random' $null $null @{FROM=$a;TO=$b} $null }
function rXpos([ref]$d){ Bk $d 'motion_xposition' $null $null $null $null }
function rYpos([ref]$d){ Bk $d 'motion_yposition' $null $null $null $null }
function rMousex([ref]$d){ Bk $d 'sensing_mousex' $null $null $null $null }
function rTouching([ref]$d,$name){ $m=Bk $d 'sensing_touchingobjectmenu' $null $null $null @{TOUCHINGOBJECTMENU=@($name,$null)} $true; Bk $d 'sensing_touchingobject' $null $null @{TOUCHINGOBJECTMENU=@(1,$m)} $null }
function rLI([ref]$d,$ln,$lid,$idx){ Bk $d 'data_itemoflist' $null $null @{INDEX=$idx} @{LIST=@($ln,$lid)} }
function rOf([ref]$d,$prop,$obj){ $m=Bk $d 'sensing_of_object_menu' $null $null $null @{OBJECT=@($obj,$null)} $true; Bk $d 'sensing_of' $null $null @{OBJECT=@(1,$m)} @{PROPERTY=@($prop,$null)} }
function rCosNum([ref]$d){ Bk $d 'looks_costumenumbername' $null $null $null @{NUMBER_NAME=@('number',$null)} }

function sFlag([ref]$d,[int]$x=20,[int]$y=20){ Bk $d 'event_whenflagclicked' $null $null $null $null $false $true $x $y }
function sCS([ref]$d,[int]$x=400,[int]$y=20){ Bk $d 'event_whenIstartasaclone' $null $null $null $null $false $true $x $y }
function sRecv([ref]$d,$name,$mid,[int]$x=700,[int]$y=20){ Bk $d 'event_whenbroadcastreceived' $null $null $null @{BROADCAST_OPTION=@($name,$mid)} $false $true $x $y }
function sBcast([ref]$d,$name,$mid){ $m=Bk $d 'event_broadcast_menu' $null $null $null @{BROADCAST_OPTION=@($name,$mid)} $true; Bk $d 'event_broadcast' $null $null @{BROADCAST_INPUT=@(1,$m)} $null }
function sBcastW([ref]$d,$name,$mid){ $m=Bk $d 'event_broadcast_menu' $null $null $null @{BROADCAST_OPTION=@($name,$mid)} $true; Bk $d 'event_broadcastandwait' $null $null @{BROADCAST_INPUT=@(1,$m)} $null }
function sGoto([ref]$d,$xv,$yv){ Bk $d 'motion_gotoxy' $null $null @{X=$xv;Y=$yv} $null }
function sSetx([ref]$d,$xv){ Bk $d 'motion_setx' $null $null @{X=$xv} $null }
function sSety([ref]$d,$yv){ Bk $d 'motion_sety' $null $null @{Y=$yv} $null }
function sChx([ref]$d,$dx){ Bk $d 'motion_changexby' $null $null @{DX=$dx} $null }
function sChy([ref]$d,$dy){ Bk $d 'motion_changeyby' $null $null @{DY=$dy} $null }
function sShow([ref]$d){ Bk $d 'looks_show' $null $null $null $null }
function sHide([ref]$d){ Bk $d 'looks_hide' $null $null $null $null }
function sCosV([ref]$d,$val){ Bk $d 'looks_switchcostumeto' $null $null @{COSTUME=$val} $null }
function sEff([ref]$d,$e,$val){ Bk $d 'looks_seteffectto' $null $null @{VALUE=$val} @{EFFECT=@($e,$null)} }
function sClrEff([ref]$d){ Bk $d 'looks_cleargraphiceffects' $null $null $null $null }
function sSayS([ref]$d,$msg,[int]$dur){ Bk $d 'looks_sayforsecs' $null $null @{MESSAGE=@(1,@(10,$msg));SECS=@(1,@(4,"$dur"))} $null }
function sSetSize([ref]$d,$sz){ Bk $d 'looks_setsizeto' $null $null @{SIZE=$sz} $null }
function sSetv([ref]$d,$n,$vid,$val){ Bk $d 'data_setvariableto' $null $null @{VALUE=$val} @{VARIABLE=@($n,$vid)} }
function sChv([ref]$d,$n,$vid,$val){ Bk $d 'data_changevariableby' $null $null @{VALUE=$val} @{VARIABLE=@($n,$vid)} }
function sAddL([ref]$d,$ln,$lid,$item){ Bk $d 'data_addtolist' $null $null @{ITEM=$item} @{LIST=@($ln,$lid)} }
function sDelL([ref]$d,$ln,$lid){ Bk $d 'data_deletealloflist' $null $null $null @{LIST=@($ln,$lid)} }
function sRepL([ref]$d,$ln,$lid,$idx,$item){ Bk $d 'data_replaceitemoflist' $null $null @{INDEX=$idx;ITEM=$item} @{LIST=@($ln,$lid)} }
function sWait([ref]$d,$dur){ Bk $d 'control_wait' $null $null @{DURATION=$dur} $null }
function sFv([ref]$d){ Bk $d 'control_forever' $null $null $null $null }
function sRep([ref]$d,$t){ Bk $d 'control_repeat' $null $null @{TIMES=$t} $null }
function sRepU([ref]$d,$cond){ Bk $d 'control_repeat_until' $null $null @{CONDITION=$cond} $null }
function sIf([ref]$d,$c){ Bk $d 'control_if' $null $null @{CONDITION=$c} $null }
function sIfe([ref]$d,$c){ Bk $d 'control_if_else' $null $null @{CONDITION=$c} $null }
function sClone([ref]$d){ $m=Bk $d 'control_create_clone_of_menu' $null $null $null @{CLONE_OPTION=@('_myself_',$null)} $true; Bk $d 'control_create_clone_of' $null $null @{CLONE_OPTION=@(1,$m)} $null }
function sDelC([ref]$d){ Bk $d 'control_delete_this_clone' $null $null $null $null }
function sStop([ref]$d){ Bk $d 'control_stop' $null $null $null @{STOP_OPTION=@('all',$null)} }

# ═══════════════════ BALLE ════════════════════════════════════════════════════
$bd = NewDict
$f=sFlag ([ref]$bd)
$i0=sSetv ([ref]$bd) 'score' $Vs['score'] (N 0)
$i1=sSetv ([ref]$bd) 'vies'  $Vs['vies']  (N 3)
$i2=sSetv ([ref]$bd) 'speed_factor' $Vs['speed_factor'] (N 1)
$i3=sSetv ([ref]$bd) 'pad_large' $Vs['pad_large'] (N 0)
$i4=sGoto ([ref]$bd) (N 0) (N -100)
$i5=sSetv ([ref]$bd) 'bvx' $Vs['bvx'] (NR (rRand ([ref]$bd) (N -4) (N 4)))
$i6=sSetv ([ref]$bd) 'bvy' $Vs['bvy'] (N 5)
$i7=sClrEff ([ref]$bd); $i_hide=sHide ([ref]$bd)
# Attendre 4 secondes que les briques se créent toutes
$wait_init=sWait ([ref]$bd) (N 4); $i8=sShow ([ref]$bd); $fv=sFv ([ref]$bd)
Lk ([ref]$bd) $f $i0; Lk ([ref]$bd) $i0 $i1; Lk ([ref]$bd) $i1 $i2; Lk ([ref]$bd) $i2 $i3
Lk ([ref]$bd) $i3 $i4; Lk ([ref]$bd) $i4 $i5; Lk ([ref]$bd) $i5 $i6
Lk ([ref]$bd) $i6 $i7; Lk ([ref]$bd) $i7 $i_hide; Lk ([ref]$bd) $i_hide $wait_init
Lk ([ref]$bd) $wait_init $i8; Lk ([ref]$bd) $i8 $fv

# Corps du forever — mouvement avec speed_factor
$bvx_sf = rMul ([ref]$bd) (VR ([ref]$bd) 'bvx' $Vs['bvx']) (VR ([ref]$bd) 'speed_factor' $Vs['speed_factor'])
$m1 = sChx ([ref]$bd) (NR $bvx_sf)
$bvy_sf = rMul ([ref]$bd) (VR ([ref]$bd) 'bvy' $Vs['bvy']) (VR ([ref]$bd) 'speed_factor' $Vs['speed_factor'])
$m2 = sChy ([ref]$bd) (NR $bvy_sf)

# Mur droit
$c1=rGt ([ref]$bd) (NR (rXpos ([ref]$bd))) (N 222)
$t1=sSetv ([ref]$bd) 'bvx' $Vs['bvx'] (NR (rSub ([ref]$bd) (N 0) (NR (rAbs ([ref]$bd) (VR ([ref]$bd) 'bvx' $Vs['bvx'])))))
$w1=sSetx ([ref]$bd) (N 220); Lk ([ref]$bd) $t1 $w1
$f1=sIf ([ref]$bd) (CN $c1); At ([ref]$bd) $f1 $t1

# Mur gauche
$c2=rLt ([ref]$bd) (NR (rXpos ([ref]$bd))) (N -222)
$t2=sSetv ([ref]$bd) 'bvx' $Vs['bvx'] (NR (rAbs ([ref]$bd) (VR ([ref]$bd) 'bvx' $Vs['bvx'])))
$w2=sSetx ([ref]$bd) (N -220); Lk ([ref]$bd) $t2 $w2
$f2=sIf ([ref]$bd) (CN $c2); At ([ref]$bd) $f2 $t2

# Plafond
$c3=rGt ([ref]$bd) (NR (rYpos ([ref]$bd))) (N 162)
$t3=sSetv ([ref]$bd) 'bvy' $Vs['bvy'] (NR (rSub ([ref]$bd) (N 0) (NR (rAbs ([ref]$bd) (VR ([ref]$bd) 'bvy' $Vs['bvy'])))))
$f3=sIf ([ref]$bd) (CN $c3); At ([ref]$bd) $f3 $t3

# Raquette (angle selon position)
$tr=rTouching ([ref]$bd) 'Raquette'
$bvn=rLt ([ref]$bd) (VR ([ref]$bd) 'bvy' $Vs['bvy']) (N 0)
$c4=rAnd ([ref]$bd) (CN $tr) (CN $bvn)
$padx=rOf ([ref]$bd) 'x position' 'Raquette'
$diff=rSub ([ref]$bd) (NR (rXpos ([ref]$bd))) (NR $padx)
$nbvx=rDiv ([ref]$bd) (NR $diff) (N 10)
$p1=sSetv ([ref]$bd) 'bvx' $Vs['bvx'] (NR $nbvx)
$p2=sSetv ([ref]$bd) 'bvy' $Vs['bvy'] (NR (rAbs ([ref]$bd) (VR ([ref]$bd) 'bvy' $Vs['bvy'])))
$p3=sSety ([ref]$bd) (N -148); Lk ([ref]$bd) $p1 $p2; Lk ([ref]$bd) $p2 $p3
$f4=sIf ([ref]$bd) (CN $c4); At ([ref]$bd) $f4 $p1

# Brique
$tbr=rTouching ([ref]$bd) 'Brique'
$b1=sSetv ([ref]$bd) 'bvy' $Vs['bvy'] (NR (rSub ([ref]$bd) (N 0) (VR ([ref]$bd) 'bvy' $Vs['bvy'])))
$b2=sBcastW ([ref]$bd) 'frappe' $BRs['frappe']; Lk ([ref]$bd) $b1 $b2
$f5=sIf ([ref]$bd) (CN $tbr); At ([ref]$bd) $f5 $b1

# Balle perdue
$c5=rLt ([ref]$bd) (NR (rYpos ([ref]$bd))) (N -170)
$l1=sChv ([ref]$bd) 'vies' $Vs['vies'] (N -1)
$cgo=rEq ([ref]$bd) (VR ([ref]$bd) 'vies' $Vs['vies']) (N 0)
$go1=sBcast ([ref]$bd) 'perdu' $BRs['perdu']; $go2=sStop ([ref]$bd); Lk ([ref]$bd) $go1 $go2
$ifgo=sIf ([ref]$bd) (CN $cgo); At ([ref]$bd) $ifgo $go1
$r1=sGoto ([ref]$bd) (N 0) (N -100)
$r2=sSetv ([ref]$bd) 'bvx' $Vs['bvx'] (NR (rRand ([ref]$bd) (N -4) (N 4)))
$r3=sSetv ([ref]$bd) 'bvy' $Vs['bvy'] (N 5)
$r4=sWait ([ref]$bd) (N 1)
Lk ([ref]$bd) $l1 $ifgo; Lk ([ref]$bd) $ifgo $r1; Lk ([ref]$bd) $r1 $r2; Lk ([ref]$bd) $r2 $r3; Lk ([ref]$bd) $r3 $r4
$f6=sIf ([ref]$bd) (CN $c5); At ([ref]$bd) $f6 $l1

Lk ([ref]$bd) $m1 $m2; Lk ([ref]$bd) $m2 $f1; Lk ([ref]$bd) $f1 $f2; Lk ([ref]$bd) $f2 $f3
Lk ([ref]$bd) $f3 $f4; Lk ([ref]$bd) $f4 $f5; Lk ([ref]$bd) $f5 $f6
At ([ref]$bd) $fv $m1

$rp=sRecv ([ref]$bd) 'perdu' $BRs['perdu'] 300 20
$sg=sSayS ([ref]$bd) 'GAME OVER !' 3; Lk ([ref]$bd) $rp $sg
$ballBlocks=$bd

# ═══════════════════ RAQUETTE ══════════════════════════════════════════════════
$pd = NewDict
$f=sFlag ([ref]$pd); $sh=sShow ([ref]$pd); $fvp=sFv ([ref]$pd)
Lk ([ref]$pd) $f $sh; Lk ([ref]$pd) $sh $fvp

$mx=rMousex ([ref]$pd)
$g=sGoto ([ref]$pd) (NR $mx) (N -155)
$c1=rGt ([ref]$pd) (NR (rXpos ([ref]$pd))) (N 195); $t1=sSetx ([ref]$pd) (N 195)
$fp1=sIf ([ref]$pd) (CN $c1); At ([ref]$pd) $fp1 $t1
$c2=rLt ([ref]$pd) (NR (rXpos ([ref]$pd))) (N -195); $t2=sSetx ([ref]$pd) (N -195)
$fp2=sIf ([ref]$pd) (CN $c2); At ([ref]$pd) $fp2 $t2

# Taille selon pad_large (powerup)
$pl_eq=rEq ([ref]$pd) (VR ([ref]$pd) 'pad_large' $Vs['pad_large']) (N 1)
$if_pl=sIfe ([ref]$pd) (CN $pl_eq)
$sz150=sSetSize ([ref]$pd) (N 150)
$sz100=sSetSize ([ref]$pd) (N 100)
At ([ref]$pd) $if_pl $sz150 'SUBSTACK'
At ([ref]$pd) $if_pl $sz100 'SUBSTACK2'

Lk ([ref]$pd) $g $fp1; Lk ([ref]$pd) $fp1 $fp2; Lk ([ref]$pd) $fp2 $if_pl
At ([ref]$pd) $fvp $g
$padBlocks=$pd

# ═══════════════════ BRIQUE ════════════════════════════════════════════════════
$bkd = NewDict
$f=sFlag ([ref]$bkd)
$d1=sDelL ([ref]$bkd) 'bpv' $Ls['bpv']; $d2=sDelL ([ref]$bkd) 'bmax' $Ls['bmax']; $hm=sHide ([ref]$bkd)

# Remplir listes HP
$sr=sSetv ([ref]$bkd) 'rangee' $Vs['rangee'] (N 0); $rr=sRep ([ref]$bkd) (N 6)
$sc=sSetv ([ref]$bkd) 'col' $Vs['col'] (N 0); $rc=sRep ([ref]$bkd) (N 8)
$hp1=rSub ([ref]$bkd) (N 6) (VR ([ref]$bkd) 'rangee' $Vs['rangee']); $a1=sAddL ([ref]$bkd) 'bpv' $Ls['bpv'] (NR $hp1)
$hp2=rSub ([ref]$bkd) (N 6) (VR ([ref]$bkd) 'rangee' $Vs['rangee']); $a2=sAddL ([ref]$bkd) 'bmax' $Ls['bmax'] (NR $hp2)
$cc1=sChv ([ref]$bkd) 'col' $Vs['col'] (N 1)
Lk ([ref]$bkd) $a1 $a2; Lk ([ref]$bkd) $a2 $cc1; At ([ref]$bkd) $rc $a1
$cr1=sChv ([ref]$bkd) 'rangee' $Vs['rangee'] (N 1)
Lk ([ref]$bkd) $sc $rc; Lk ([ref]$bkd) $rc $cr1; At ([ref]$bkd) $rr $sc

# Créer clones à leurs positions
$sr2=sSetv ([ref]$bkd) 'rangee' $Vs['rangee'] (N 0); $rr2=sRep ([ref]$bkd) (N 6)
$sc2=sSetv ([ref]$bkd) 'col' $Vs['col'] (N 0); $rc2=sRep ([ref]$bkd) (N 8)
$tx=rAdd ([ref]$bkd) (N $BX0) (NR (rMul ([ref]$bkd) (VR ([ref]$bkd) 'col' $Vs['col']) (N $BDX)))
$ty=rSub ([ref]$bkd) (N $BY0) (NR (rMul ([ref]$bkd) (VR ([ref]$bkd) 'rangee' $Vs['rangee']) (N $BDY)))
$g1=sGoto ([ref]$bkd) (NR $tx) (NR $ty)
$cos=rAdd ([ref]$bkd) (VR ([ref]$bkd) 'rangee' $Vs['rangee']) (N 1); $csw=sCosV ([ref]$bkd) (NR $cos)
$sh2=sShow ([ref]$bkd); $cl=sClone ([ref]$bkd); $hd2=sHide ([ref]$bkd)
$cc2=sChv ([ref]$bkd) 'col' $Vs['col'] (N 1)
Lk ([ref]$bkd) $g1 $csw; Lk ([ref]$bkd) $csw $sh2; Lk ([ref]$bkd) $sh2 $cl; Lk ([ref]$bkd) $cl $hd2; Lk ([ref]$bkd) $hd2 $cc2
At ([ref]$bkd) $rc2 $g1
$cr2=sChv ([ref]$bkd) 'rangee' $Vs['rangee'] (N 1)
Lk ([ref]$bkd) $sc2 $rc2; Lk ([ref]$bkd) $rc2 $cr2; At ([ref]$bkd) $rr2 $sc2
Lk ([ref]$bkd) $f $d1; Lk ([ref]$bkd) $d1 $d2; Lk ([ref]$bkd) $d2 $hm; Lk ([ref]$bkd) $hm $sr
Lk ([ref]$bkd) $sr $rr; Lk ([ref]$bkd) $rr $sr2; Lk ([ref]$bkd) $sr2 $rr2

# Démarrage clone
$cs=sCS ([ref]$bkd); $sh3=sShow ([ref]$bkd); Lk ([ref]$bkd) $cs $sh3

# Réception frappe
$rv=sRecv ([ref]$bkd) 'frappe' $BRs['frappe']
$tball=rTouching ([ref]$bkd) 'Balle'

# Index depuis position
$yp=rYpos ([ref]$bkd); $ydiff=rSub ([ref]$bkd) (N $BY0) (NR $yp)
$rowf=rDiv ([ref]$bkd) (NR $ydiff) (N $BDY); $rowr=rFloor ([ref]$bkd) (NR $rowf)
$xp=rXpos ([ref]$bkd); $xdiff=rSub ([ref]$bkd) (NR $xp) (N $BX0)
$colf=rDiv ([ref]$bkd) (NR $xdiff) (N $BDX); $colr=rFloor ([ref]$bkd) (NR $colf)
$rpart=rMul ([ref]$bkd) (NR $rowr) (N $COLS)
$idx=rAdd ([ref]$bkd) (NR $rpart) (NR $colr); $idx1=rAdd ([ref]$bkd) (NR $idx) (N 1)
$setid=sSetv ([ref]$bkd) 'mon_id' $Vs['mon_id'] (NR $idx1)
$curhp=rLI ([ref]$bkd) 'bpv' $Ls['bpv'] (VR ([ref]$bkd) 'mon_id' $Vs['mon_id'])
$setpv=sSetv ([ref]$bkd) 'mon_pv' $Vs['mon_pv'] (NR $curhp)
$newhp=rSub ([ref]$bkd) (VR ([ref]$bkd) 'mon_pv' $Vs['mon_pv']) (N 1)
$rephp=sRepL ([ref]$bkd) 'bpv' $Ls['bpv'] (VR ([ref]$bkd) 'mon_id' $Vs['mon_id']) (NR $newhp)
$chsc=sChv ([ref]$bkd) 'score' $Vs['score'] (N 10)
$maxhp=rLI ([ref]$bkd) 'bmax' $Ls['bmax'] (VR ([ref]$bkd) 'mon_id' $Vs['mon_id'])
$curAft=rSub ([ref]$bkd) (VR ([ref]$bkd) 'mon_pv' $Vs['mon_pv']) (N 1)
$ratio=rDiv ([ref]$bkd) (NR $curAft) (NR $maxhp)
$bright=rMul ([ref]$bkd) (NR (rSub ([ref]$bkd) (N 1) (NR $ratio))) (N 80)
$setbr=sEff ([ref]$bkd) 'brightness' (NR $bright)

# Mort : spawn powerup (30%) puis delete
$cdead=rEq ([ref]$bkd) (VR ([ref]$bkd) 'mon_pv' $Vs['mon_pv']) (N 1)
$ifdead=sIf ([ref]$bkd) (CN $cdead)

$rnd30=rLt ([ref]$bkd) (NR (rRand ([ref]$bkd) (N 1) (N 10))) (N 4)
$ifspawn=sIf ([ref]$bkd) (CN $rnd30)
$spux=sSetv ([ref]$bkd) 'pu_x' $Vs['pu_x'] (NR (rXpos ([ref]$bkd)))
$spuy=sSetv ([ref]$bkd) 'pu_y' $Vs['pu_y'] (NR (rYpos ([ref]$bkd)))
$sput=sSetv ([ref]$bkd) 'pu_type' $Vs['pu_type'] (NR (rRand ([ref]$bkd) (N 1) (N 3)))
$bwpu=sBcastW ([ref]$bkd) 'spawn_pu' $BRs['spawn_pu']
Lk ([ref]$bkd) $spux $spuy; Lk ([ref]$bkd) $spuy $sput; Lk ([ref]$bkd) $sput $bwpu
At ([ref]$bkd) $ifspawn $spux

$dc=sDelC ([ref]$bkd)
Lk ([ref]$bkd) $ifspawn $dc
At ([ref]$bkd) $ifdead $ifspawn

Lk ([ref]$bkd) $setid $setpv; Lk ([ref]$bkd) $setpv $rephp; Lk ([ref]$bkd) $rephp $chsc
Lk ([ref]$bkd) $chsc $setbr; Lk ([ref]$bkd) $setbr $ifdead

$ift=sIf ([ref]$bkd) (CN $tball); At ([ref]$bkd) $ift $setid; Lk ([ref]$bkd) $rv $ift
$brickBlocks=$bkd

# ═══════════════════ POWERUP ═══════════════════════════════════════════════════
$pu = NewDict

# Script 1 : drapeau vert
$f=sFlag ([ref]$pu); $hpu=sHide ([ref]$pu)
Lk ([ref]$pu) $f $hpu

# Script 2 : recevoir spawn_pu
$rspawn=sRecv ([ref]$pu) 'spawn_pu' $BRs['spawn_pu'] 20 300
$gtoPos=sGoto ([ref]$pu) (VR ([ref]$pu) 'pu_x' $Vs['pu_x']) (VR ([ref]$pu) 'pu_y' $Vs['pu_y'])
$swCos=sCosV ([ref]$pu) (VR ([ref]$pu) 'pu_type' $Vs['pu_type'])
$showPU=sShow ([ref]$pu); $clPU=sClone ([ref]$pu); $hidePU=sHide ([ref]$pu)
Lk ([ref]$pu) $rspawn $gtoPos; Lk ([ref]$pu) $gtoPos $swCos
Lk ([ref]$pu) $swCos $showPU; Lk ([ref]$pu) $showPU $clPU; Lk ([ref]$pu) $clPU $hidePU

# Script 3 : clone — chute via forever + if (plus fiable)
$cs=sCS ([ref]$pu) 400 300; $showC=sShow ([ref]$pu)
$fvpu=sFv ([ref]$pu)

# Chute : change y by -3 chaque frame
$fall=sChy ([ref]$pu) (N -3)

# Vérif raquette
$tru2=rTouching ([ref]$pu) 'Raquette'
$if_caught=sIf ([ref]$pu) (CN $tru2)

# Cache le powerup dès qu'il est attrapé
$hideCatch=sHide ([ref]$pu)

# Type 1 : +1 vie
$cn1=rEq ([ref]$pu) (NR (rCosNum ([ref]$pu))) (N 1)
$if1=sIf ([ref]$pu) (CN $cn1)
$chvie=sChv ([ref]$pu) 'vies' $Vs['vies'] (N 1)
At ([ref]$pu) $if1 $chvie

# Type 2 : grande raquette 8 secondes
$cn2=rEq ([ref]$pu) (NR (rCosNum ([ref]$pu))) (N 2)
$if2=sIf ([ref]$pu) (CN $cn2)
$setPL1=sSetv ([ref]$pu) 'pad_large' $Vs['pad_large'] (N 1)
$waitPL=sWait ([ref]$pu) (N 8)
$setPL0=sSetv ([ref]$pu) 'pad_large' $Vs['pad_large'] (N 0)
Lk ([ref]$pu) $setPL1 $waitPL; Lk ([ref]$pu) $waitPL $setPL0
At ([ref]$pu) $if2 $setPL1

# Type 3 : balle lente 6 secondes
$cn3=rEq ([ref]$pu) (NR (rCosNum ([ref]$pu))) (N 3)
$if3=sIf ([ref]$pu) (CN $cn3)
$setSF06=sSetv ([ref]$pu) 'speed_factor' $Vs['speed_factor'] (N 0.6)
$waitSF=sWait ([ref]$pu) (N 6)
$setSF1=sSetv ([ref]$pu) 'speed_factor' $Vs['speed_factor'] (N 1)
Lk ([ref]$pu) $setSF06 $waitSF; Lk ([ref]$pu) $waitSF $setSF1
At ([ref]$pu) $if3 $setSF06

# Chaîne interne du if_caught : hide → if1 → if2 → if3 → delC
$delC_catch=sDelC ([ref]$pu)
Lk ([ref]$pu) $hideCatch $if1; Lk ([ref]$pu) $if1 $if2; Lk ([ref]$pu) $if2 $if3; Lk ([ref]$pu) $if3 $delC_catch
At ([ref]$pu) $if_caught $hideCatch

# Vérif sorti bas de l'écran (séparé, après if_caught)
$y_gone=rLt ([ref]$pu) (NR (rYpos ([ref]$pu))) (N -178)
$if_gone=sIf ([ref]$pu) (CN $y_gone)
$delC_gone=sDelC ([ref]$pu)
At ([ref]$pu) $if_gone $delC_gone

# Chaîne dans le forever : fall → if_caught → if_gone
Lk ([ref]$pu) $fall $if_caught; Lk ([ref]$pu) $if_caught $if_gone
At ([ref]$pu) $fvpu $fall

# Script clone : show → forever
Lk ([ref]$pu) $cs $showC; Lk ([ref]$pu) $showC $fvpu
$puBlocks=$pu

# ═══════════════════ SVG COSTUMES ═════════════════════════════════════════════

# --- Fond étoilé ---
$stars='<circle cx="15" cy="20" r="1" fill="white" opacity="0.8"/>'+
       '<circle cx="45" cy="9"  r="0.8" fill="white" opacity="0.6"/>'+
       '<circle cx="80" cy="28" r="1.1" fill="white" opacity="0.9"/>'+
       '<circle cx="120" cy="14" r="0.7" fill="white" opacity="0.7"/>'+
       '<circle cx="160" cy="5"  r="1"   fill="white" opacity="0.8"/>'+
       '<circle cx="200" cy="22" r="0.9" fill="white" opacity="0.7"/>'+
       '<circle cx="248" cy="8"  r="1.1" fill="white" opacity="0.85"/>'+
       '<circle cx="300" cy="25" r="0.8" fill="white" opacity="0.6"/>'+
       '<circle cx="340" cy="12" r="1"   fill="white" opacity="0.9"/>'+
       '<circle cx="382" cy="20" r="0.8" fill="white" opacity="0.7"/>'+
       '<circle cx="422" cy="7"  r="1.2" fill="white" opacity="0.85"/>'+
       '<circle cx="460" cy="24" r="0.7" fill="white" opacity="0.75"/>'+
       '<circle cx="28" cy="52" r="0.9" fill="white" opacity="0.7"/>'+
       '<circle cx="72" cy="60" r="1"   fill="white" opacity="0.8"/>'+
       '<circle cx="115" cy="44" r="0.8" fill="white" opacity="0.9"/>'+
       '<circle cx="155" cy="56" r="1.1" fill="white" opacity="0.7"/>'+
       '<circle cx="198" cy="40" r="0.9" fill="white" opacity="0.8"/>'+
       '<circle cx="232" cy="65" r="0.7" fill="white" opacity="0.6"/>'+
       '<circle cx="272" cy="48" r="1"   fill="white" opacity="0.85"/>'+
       '<circle cx="318" cy="58" r="0.8" fill="white" opacity="0.7"/>'+
       '<circle cx="358" cy="44" r="1.1" fill="white" opacity="0.9"/>'+
       '<circle cx="402" cy="60" r="0.9" fill="white" opacity="0.7"/>'+
       '<circle cx="442" cy="50" r="1"   fill="white" opacity="0.8"/>'+
       '<circle cx="468" cy="40" r="0.8" fill="white" opacity="0.9"/>'+
       '<circle cx="8"   cy="315" r="0.9" fill="white" opacity="0.6"/>'+
       '<circle cx="102" cy="310" r="1"   fill="white" opacity="0.8"/>'+
       '<circle cx="198" cy="325" r="0.8" fill="white" opacity="0.7"/>'+
       '<circle cx="312" cy="318" r="1.1" fill="white" opacity="0.9"/>'+
       '<circle cx="400" cy="330" r="0.9" fill="white" opacity="0.7"/>'+
       '<circle cx="452" cy="312" r="0.8" fill="white" opacity="0.85"/>'

$bgSvg='<svg xmlns="http://www.w3.org/2000/svg" width="480" height="360">'+
       '<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">'+
       '<stop offset="0%" stop-color="#07071a"/><stop offset="100%" stop-color="#18072a"/>'+
       '</linearGradient></defs>'+
       '<rect width="480" height="360" fill="url(#bg)"/>'+
       $stars+
       '<line x1="0" y1="350" x2="480" y2="350" stroke="rgba(80,80,255,0.1)" stroke-width="1"/>'+
       '</svg>'
$bgSVG=utf8 $bgSvg

# --- Balle ---
$ballSvg='<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16">'+
         '<defs><radialGradient id="rg" cx="35%" cy="35%">'+
         '<stop offset="0%" stop-color="white"/>'+
         '<stop offset="65%" stop-color="#d0e8ff"/>'+
         '<stop offset="100%" stop-color="#7ab8f5"/>'+
         '</radialGradient></defs>'+
         '<circle cx="8" cy="8" r="8" fill="url(#rg)"/>'+
         '<circle cx="5" cy="5" r="2.5" fill="white" opacity="0.55"/>'+
         '</svg>'
$ballSVG=utf8 $ballSvg

# --- Raquette ---
$padSvg='<svg xmlns="http://www.w3.org/2000/svg" width="80" height="14">'+
        '<defs><linearGradient id="pg" x1="0" y1="0" x2="0" y2="1">'+
        '<stop offset="0%" stop-color="#a8f0ff"/>'+
        '<stop offset="100%" stop-color="#0090cc"/>'+
        '</linearGradient></defs>'+
        '<rect width="80" height="14" rx="7" fill="url(#pg)"/>'+
        '<rect x="5" y="2" width="70" height="4" rx="2" fill="white" opacity="0.35"/>'+
        '<circle cx="7" cy="7" r="3" fill="white" opacity="0.2"/>'+
        '<circle cx="73" cy="7" r="3" fill="white" opacity="0.2"/>'+
        '</svg>'
$padSVG=utf8 $padSvg

# --- Briques (6 costumes avec dégradé et points HP) ---
function mkBrickSvg($color, $lighter, $hp) {
    $dots=""
    $ds = 48.0/($hp+1)
    for($j=1;$j-le$hp;$j++){
        $dx=[math]::Round($j*$ds,1)
        $dots+="<circle cx='$dx' cy='13' r='1.5' fill='white' opacity='0.65'/>"
    }
    return '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="16">'+
           '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'+
           "<stop offset='0%' stop-color='$lighter'/>"+
           "<stop offset='100%' stop-color='$color'/>"+
           '</linearGradient></defs>'+
           "<rect width='48' height='16' rx='3' fill='url(#g)'/>"+
           "<rect x='2' y='2' width='44' height='5' rx='2' fill='white' opacity='0.22'/>"+
           $dots+
           '</svg>'
}

# --- Powerups (3 costumes) ---
function mkPuSvg($color, $lighter, $label) {
    return '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="14">'+
           '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'+
           "<stop offset='0%' stop-color='$lighter'/>"+
           "<stop offset='100%' stop-color='$color'/>"+
           '</linearGradient></defs>'+
           "<rect width='22' height='14' rx='7' fill='url(#g)'/>"+
           "<rect x='2' y='2' width='18' height='4' rx='2' fill='white' opacity='0.3'/>"+
           "<text x='11' y='10' text-anchor='middle' font-family='Arial' font-weight='bold' font-size='7' fill='white'>$label</text>"+
           '</svg>'
}

function mkCos($name,[byte[]]$bytes,[int]$cx,[int]$cy){
    $aid=md5b $bytes; wf "$aid.svg" $bytes
    @{name=$name;bitmapResolution=1;dataFormat='svg';assetId=$aid;md5ext="$aid.svg";rotationCenterX=$cx;rotationCenterY=$cy}
}

$bgid=md5b $bgSVG; wf "$bgid.svg" $bgSVG
$balc=mkCos 'balle'    $ballSVG 8 8
$padc=mkCos 'raquette' $padSVG 40 7

$bkCos=@()
$bkHPs=@(6,5,4,3,2,1)
for($i=0;$i-lt6;$i++){
    $sv=utf8(mkBrickSvg $RC[$i] $RCL[$i] $bkHPs[$i])
    $bkCos+=mkCos "brique_$($i+1)" $sv 24 8
}

$puColors  =@('#27ae60','#2980b9','#e67e22')
$puLighter =@('#5dde8a','#5dade2','#f5b342')
$puLabels  =@('+VIE','+PAD','SLOW')
$puCos=@()
for($i=0;$i-lt3;$i++){
    $sv=utf8(mkPuSvg $puColors[$i] $puLighter[$i] $puLabels[$i])
    $puCos+=mkCos "powerup_$($i+1)" $sv 11 7
}

# ═══════════════════ ASSEMBLAGE PROJET ════════════════════════════════════════
$stV=@{};foreach($k in $Vs.Keys){$stV[$Vs[$k]]=@($k,0)}
$stL=@{};foreach($k in $Ls.Keys){$stL[$Ls[$k]]=@($k,@())}
$stB=@{};foreach($k in $BRs.Keys){$stB[$BRs[$k]]=$k}

$proj=@{
  targets=@(
    @{isStage=$true;name='Stage';variables=$stV;lists=$stL;broadcasts=$stB;blocks=@{};comments=@{};currentCostume=0
      costumes=@(@{name='fond';bitmapResolution=1;dataFormat='svg';assetId=$bgid;md5ext="$bgid.svg";rotationCenterX=240;rotationCenterY=180})
      sounds=@();volume=100;layerOrder=0;tempo=60;videoTransparency=50;videoState='on';textToSpeechLanguage=$null},

    @{isStage=$false;name='Balle';variables=@{};lists=@{};broadcasts=@{}
      blocks=$ballBlocks;comments=@{};currentCostume=0;costumes=@($balc);sounds=@()
      volume=100;layerOrder=4;visible=$true;x=0;y=-100;size=100;direction=90;draggable=$false;rotationStyle='all around'},

    @{isStage=$false;name='Raquette';variables=@{};lists=@{};broadcasts=@{}
      blocks=$padBlocks;comments=@{};currentCostume=0;costumes=@($padc);sounds=@()
      volume=100;layerOrder=3;visible=$true;x=0;y=-155;size=100;direction=90;draggable=$false;rotationStyle="don't rotate"},

    @{isStage=$false;name='Brique';variables=@{};lists=@{};broadcasts=@{}
      blocks=$brickBlocks;comments=@{};currentCostume=0;costumes=$bkCos;sounds=@()
      volume=100;layerOrder=2;visible=$true;x=0;y=0;size=100;direction=90;draggable=$false;rotationStyle="don't rotate"},

    @{isStage=$false;name='Powerup';variables=@{};lists=@{};broadcasts=@{}
      blocks=$puBlocks;comments=@{};currentCostume=0;costumes=$puCos;sounds=@()
      volume=100;layerOrder=1;visible=$false;x=0;y=0;size=100;direction=90;draggable=$false;rotationStyle="don't rotate"}
  )
  monitors=@(
    @{id=$Vs['score'];mode='default';opcode='data_variable';params=@{VARIABLE='score'};spriteName=$null;value=0;width=0;height=0;x=5;y=5;visible=$true;sliderMin=0;sliderMax=100;isDiscrete=$true},
    @{id=$Vs['vies'];mode='default';opcode='data_variable';params=@{VARIABLE='vies'};spriteName=$null;value=3;width=0;height=0;x=5;y=30;visible=$true;sliderMin=0;sliderMax=100;isDiscrete=$true}
  )
  extensions=@()
  meta=@{semver='3.0.0';vm='0.2.0';agent='CasseBriquesUltra'}
}

wf 'project.json' (utf8($proj | ConvertTo-Json -Depth 30 -Compress))

$out='c:\Users\tsumu\Documents\projet_test\casse_briques.sb3'
if(Test-Path $out){Remove-Item $out -Force}
[System.IO.Compression.ZipFile]::CreateFromDirectory($tmp,$out)
$sz=(Get-Item $out).Length
Write-Host "SUCCES: $out ($sz octets)"
Write-Host "  Sprites: Balle, Raquette, Brique, Powerup"
Write-Host "  Powerups: +VIE (vert) | +PAD/grande raquette (bleu) | SLOW/balle lente (orange)"
Write-Host "  PV par rangee (haut->bas): 6-5-4-3-2-1"
