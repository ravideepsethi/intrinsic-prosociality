"""Convert bundled P052 outlines to TrueType for Matplotlib PDF embedding.

The converted font files remain under the supplied P052 font license.
Source font outlines and license are bundled. The 0.25-unit curve tolerance
affects font outlines only; this utility never reads or changes plotted data.
"""
from pathlib import Path
from fontTools.ttLib import TTFont
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.cu2quPen import Cu2QuPen


def main():
    root=Path(__file__).resolve().parents[1]/'fonts'
    for suffix,style in [('Roman','Regular'),('Bold','Bold')]:
        original=TTFont(root/f'P052-{suffix}.otf')
        builder=FontBuilder(original['head'].unitsPerEm,isTTF=True)
        order=original.getGlyphOrder()
        builder.setupGlyphOrder(order)
        builder.setupCharacterMap(original.getBestCmap())
        source=original.getGlyphSet();glyphs={}
        for name in order:
            pen=TTGlyphPen(source)
            source[name].draw(Cu2QuPen(pen,max_err=.25,reverse_direction=True))
            glyphs[name]=pen.glyph()
        builder.setupGlyf(glyphs)
        builder.setupHorizontalMetrics(original['hmtx'].metrics)
        h=original['hhea']
        builder.setupHorizontalHeader(ascent=h.ascent,descent=h.descent,lineGap=h.lineGap)
        builder.setupNameTable({'familyName':'P052 Figures','styleName':style,
            'uniqueFontIdentifier':f'P052-Figures-{style}-1.0',
            'fullName':f'P052 Figures {style}','psName':f'P052Figures-{style}',
            'version':'Version 1.0; outline-format conversion of P052',
            'copyright':original['name'].getDebugName(0) or 'URW Software; see P052-COPYRIGHT.txt',
            'licenseDescription':'AGPL-3 with Font exception; see bundled P052-COPYRIGHT.txt'})
        os2=original['OS/2']
        builder.setupOS2(sTypoAscender=os2.sTypoAscender,sTypoDescender=os2.sTypoDescender,
            sTypoLineGap=os2.sTypoLineGap,usWinAscent=os2.usWinAscent,usWinDescent=os2.usWinDescent,
            usWeightClass=os2.usWeightClass,usWidthClass=os2.usWidthClass,
            fsType=os2.fsType,fsSelection=os2.fsSelection)
        post=original['post']
        builder.setupPost(italicAngle=post.italicAngle,underlinePosition=post.underlinePosition,
                          underlineThickness=post.underlineThickness,isFixedPitch=post.isFixedPitch)
        builder.font['head'].macStyle=original['head'].macStyle
        for tag in ['GPOS','GSUB','GDEF','kern']:
            if tag in original:
                builder.font[tag]=original[tag]
        target=root/f'P052Figures-{style}.ttf'
        builder.save(target)
        print(target.name)


if __name__=='__main__':main()
