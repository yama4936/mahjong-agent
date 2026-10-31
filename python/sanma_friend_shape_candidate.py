"""Bind existing resident sanma shape hypotheses to physical positions.

These are not live-tile counts or a safety/riichi assessment. Never use an
unknown riichi status to authorize a hand discard.
"""
import math


def friend_shape_candidate(receipt):
    try:
        source=receipt['sourceObservation']; report=source['report']; digest=receipt['digest']
        structural=receipt['structuralPositions']; hand=report['hand']; geometry=report['handGeometry']
        if (source['digest']!=digest or report['digest']!=digest or structural['digest']!=digest
                or structural['status']!='blocked' or structural['operationAuthorized'] is not False
                or hand['status']!='candidate' or geometry['status']!='candidate'):
            raise ValueError('frame or structural evidence unavailable')
        tiles=hand['value']['tiles']; points=geometry['value']['clickPoints']; rows=structural['candidates']
        if (not isinstance(tiles,list) or len(tiles)!=14 or not isinstance(points,list) or len(points)!=14
                or not isinstance(rows,list) or len(rows)!=len(set(tiles))):
            raise ValueError('incomplete hand, points or shape candidates')
        seen=set()
        for row in rows:
            tile=row['tile']; shanten=row['shanten']; total=row['maximumUnseenTotal']; positions=row['positions']; draws=row['improvingDraws']
            if (tile in seen or tile not in tiles or type(shanten)!=int or not -1<=shanten<=8
                    or type(total)!=int or total<0 or not isinstance(draws,list) or not isinstance(positions,list)):
                raise ValueError('malformed shape candidate')
            seen.add(tile)
            if any(not isinstance(x,dict) or type(x.get('maximumUnseen'))!=int or not 0<x['maximumUnseen']<=4 for x in draws) or sum(x['maximumUnseen'] for x in draws)!=total:
                raise ValueError('improving draw upper bound unavailable')
            indices=[i for i,t in enumerate(tiles) if t==tile]
            if len(positions)!=len(indices):raise ValueError('incomplete physical positions')
            for position,i in zip(positions,indices):
                p=points[i]
                if (position.get('index')!=i or position.get('point')!=p or not isinstance(p,dict)
                        or set(p)!={'x','y'} or any(type(p[k]) not in (int,float) or not math.isfinite(p[k]) for k in ('x','y'))):
                    raise ValueError('physical position mismatch')
        best=min(rows,key=lambda r:(r['shanten'],-r['maximumUnseenTotal'],r['tile']))
        pos=best['positions'][0]
        return {'status':'candidate','tile':best['tile'],'index':pos['index'],'point':pos['point'],
                'shanten':best['shanten'],'improvingDrawUpperBound':best['maximumUnseenTotal'],
                'confirmed':False,'operationAuthorized':False,'riichiStatus':'unknown',
                'limitations':['recognized labels unverified','public tiles and live counts incomplete','danger and value unassessed']}
    except (KeyError,TypeError,ValueError,IndexError):
        return {'status':'unresolved','confirmed':False,'operationAuthorized':False,
                'reason':'incomplete, inconsistent, or unverified shape evidence'}
