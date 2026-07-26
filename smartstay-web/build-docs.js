// Transform the self-contained artifact into docs/index.html for GitHub Pages:
//  - wrap in a full HTML document (doctype/head meta/favicon)
//  - inject real Unsplash property photos (they load in a real browser on Pages)
//  - use a distinct LS_KEY so the Pages build reseeds independently
const fs=require('fs');
const path=require('path');
// Source artifact and output live in the repo; run with `node smartstay-web/build-docs.js`.
const SRC=path.join(__dirname,'smartstay.src.html');
const OUT=path.join(__dirname,'..','docs','index.html');

let art=fs.readFileSync(SRC,'utf8');

// 1) distinct storage key for the Pages deployment
art=art.replace("const LS_KEY='smartstay_demo_db_v3';","const LS_KEY='smartstay_pages_db_v4';");

// 2) real-photo tables, injected right after `let DB;`
const PHOTOBLOCK=`
const _U=(id)=>'https://images.unsplash.com/photo-'+id+'?auto=format&fit=crop&w=1200&q=80';
const _IDS={
 'Malibu':['1613490493576-7fde63acd811','1600585154340-be6161a56a0c','1600566753086-00f18fb6b3ea','1600210492486-724fe5c67fb0','1600607687939-ce8a6c25118c'],
 'Aspen':['1518780664697-55e3ad937233','1493809842364-78817add7ffb','1600585152220-90363fe7e115','1502672260266-1c1ef2d93688','1522708323590-d24dbb6b0267'],
 'Austin':['1560448204-e02f11c3d0e2','1502005229762-cf1b2da7c5d6','1600121848594-d8644e57abab','1600047509807-ba8f99d2cdde'],
 'Miami Beach':['1580587771525-78b9dba3b914','1600607687939-ce8a6c25118c','1600566753086-00f18fb6b3ea','1600585154340-be6161a56a0c'],
 'Lake Tahoe':['1449844908441-8829872d2607','1493809842364-78817add7ffb','1502672260266-1c1ef2d93688','1600585152220-90363fe7e115'],
 'Nashville':['1512917774080-9991f1c4c750','1600596542815-ffad4c1539a9','1600607687939-ce8a6c25118c','1600566753086-00f18fb6b3ea'],
 'Scottsdale':['1568605114967-8130f3a36994','1600585154340-be6161a56a0c','1600210492486-724fe5c67fb0','1600607687939-ce8a6c25118c'],
 'Savannah':['1570129477492-45c003edd2be','1600596542815-ffad4c1539a9','1522708323590-d24dbb6b0267','1600566753086-00f18fb6b3ea'],
 'Big Bear Lake':['1493809842364-78817add7ffb','1518780664697-55e3ad937233','1502672260266-1c1ef2d93688','1600585152220-90363fe7e115'],
 'Brooklyn':['1600121848594-d8644e57abab','1560448204-e02f11c3d0e2','1502005229762-cf1b2da7c5d6','1600047509807-ba8f99d2cdde'],
 'Sedona':['1600585152220-90363fe7e115','1568605114967-8130f3a36994','1600210492486-724fe5c67fb0','1600607687939-ce8a6c25118c'],
 'Outer Banks':['1600596542815-ffad4c1539a9','1512917774080-9991f1c4c750','1449844908441-8829872d2607','1600566753086-00f18fb6b3ea'],
};
const PHOTOS_BY_CITY={};for(const [c,ids] of Object.entries(_IDS)) PHOTOS_BY_CITY[c]=ids.map(_U);
const PRESET_REAL=['1568605114967-8130f3a36994','1512917774080-9991f1c4c750','1600585154340-be6161a56a0c','1600596542815-ffad4c1539a9','1600607687939-ce8a6c25118c','1600566753086-00f18fb6b3ea','1570129477492-45c003edd2be','1449844908441-8829872d2607','1613490493576-7fde63acd811','1502672260266-1c1ef2d93688','1560448204-e02f11c3d0e2','1493809842364-78817add7ffb'].map(_U);
`;
if(!art.includes('let DB;')) throw new Error('anchor `let DB;` not found');
art=art.replace('let DB;','let DB;\n'+PHOTOBLOCK);

// 3) use the real photos for seeded listings
const seedBefore="photos:photoSet(theme,`${it.city}, ${it.state}`)";
const seedAfter ="photos:(PHOTOS_BY_CITY[it.city]||photoSet(theme,`${it.city}, ${it.state}`))";
if(!art.includes(seedBefore)) throw new Error('seed photos anchor not found');
art=art.replace(seedBefore,seedAfter);

// 4) preset upload gallery uses real photos too
const presetBefore="const PRESET_PHOTOS=Array.from({length:12},(_,i)=>svgPhoto((i*29)%360,PHOTO_EMOJI[i%PHOTO_EMOJI.length],'Your home'));";
if(!art.includes(presetBefore)) throw new Error('PRESET_PHOTOS anchor not found');
art=art.replace(presetBefore,"const PRESET_PHOTOS=PRESET_REAL;");

// 5) wrap in a full HTML document
const HEAD=`<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="SmartStay USA — rent beautiful homes across the USA. No guest booking fees, ever.">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%F0%9F%8F%A1%3C/text%3E%3C/svg%3E">
`;
// artifact starts with `<title>`; put the head meta above it, close head after </style>
art=HEAD+art;
art=art.replace('</style>\n','</style>\n</head>\n<body>\n');
art=art.replace(/\s*$/,'\n')+'</body>\n</html>\n';

fs.writeFileSync(OUT,art);
console.log('wrote',OUT,art.length,'bytes');
