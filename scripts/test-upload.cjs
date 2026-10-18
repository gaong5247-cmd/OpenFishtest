/* GH Pages upload: no PR, no token storage, just PGN+EPD blobs. */
"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");

class Element {
  constructor(id=""){
    this.id=id;this.value="";this.files=[];
    this.textContent="";this.dataset={};this.children=[];
    this.events={};this.disabled=false;this.checked=false;this.className="";
    this.classes=new Set();
    this.classList={
      add:k=>this.classes.add(k),remove:k=>this.classes.delete(k),
      contains:k=>this.classes.has(k)
    };
  }
  addEventListener(name,fn){this.events[name]=fn;}
  replaceChildren(...values){this.children=values;}
  append(...values){this.children.push(...values);}
}

function file(name,contents){
  const bytes=Buffer.from(contents);
  return {name,size:bytes.length,
    arrayBuffer:async()=>bytes.buffer.slice(
      bytes.byteOffset,bytes.byteOffset+bytes.byteLength
    )};
}

(async()=>{
  const html=fs.readFileSync("docs/upload.html","utf8");
  const js=fs.readFileSync("docs/upload.js","utf8");
  const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
  const nodes=new Map(ids.map(id=>[id,new Element(id)]));
  const get=id=>{
    assert.ok(nodes.has(id),"Missing upload UI element: "+id);
    return nodes.get(id);
  };
  const calls=[];
  const OWNER="gaong5247-cmd/OpenFishtest";
  let blobNumber=0;
  const fetchStub=async(url,options)=>{
    assert.ok(url.startsWith("https://api.github.com/"),url);
    assert.equal(options.headers.Authorization,
      "Bearer github_pat_test_scoped_private_token");
    const path=url.slice("https://api.github.com/".length);
    const payload=options.body ? JSON.parse(options.body):null;
    calls.push({method:options.method,path,payload});
    let body={};
    if(options.method==="GET"&&path==="user"){
      body={login:"gaong5247-cmd"};
    } else if(options.method==="GET"&&path==="repos/"+OWNER){
      body={full_name:OWNER,permissions:{push:true}};
    } else if(path.endsWith("/git/ref/heads/main")){
      body={object:{sha:"1".repeat(40)}};
    } else if(path.endsWith("/git/commits/"+"1".repeat(40))){
      body={tree:{sha:"2".repeat(40)}};
    } else if(path.endsWith("/git/blobs")&&options.method==="POST"){
      blobNumber++;
      assert.equal(payload.encoding,"base64");
      body={sha:String(blobNumber+2).repeat(40)};
    } else if(path.endsWith("/git/trees")){
      assert.equal(payload.base_tree,"2".repeat(40));
      assert.equal(payload.tree.length,2);
      assert.deepEqual(payload.tree.map(x=>x.path),[
        "submissions/"+"aa".repeat(12)+"/games.pgn",
        "submissions/"+"aa".repeat(12)+"/openings.epd"
      ]);
      body={sha:"5".repeat(40)};
    } else if(path.endsWith("/git/commits")&&options.method==="POST"){
      assert.deepEqual(payload.parents,["1".repeat(40)]);
      body={sha:"6".repeat(40)};
    } else if(path.endsWith("/git/refs")&&options.method==="POST"){
      assert.equal(
        payload.ref,"refs/heads/community-upload/"+"aa".repeat(12)
      );
      assert.equal(payload.sha,"6".repeat(40));
    } else {
      throw new Error("Unexpected GitHub request: "+path);
    }
    return {ok:true,json:async()=>body};
  };
  const document={
    getElementById:get,
    createElement:tag=>new Element(tag)
  };
  const context={
    window:{},document,fetch:fetchStub,
    crypto:{getRandomValues:a=>a.fill(0xaa)},
    TextDecoder,Uint8Array,
    btoa:raw=>Buffer.from(raw,"binary").toString("base64"),
    console
  };
  vm.runInNewContext(js,context,{filename:"docs/upload.js"});
  const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
  const pgn='[Event "Real match"]\n[White "Challenger"]\n'+
    '[Black "Stockless"]\n[Result "1-0"]\n\n1. e4 e5 1-0';
  const epd='rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -\n';
  get("pgn-file").files=[file("games.pgn",pgn)];
  get("epd-file").files=[file("openings.epd",epd)];
  get("pgn-file").events.change();
  get("epd-file").events.change();
  assert.equal(get("publish-button").disabled,true);
  get("github-token").value="github_pat_test_scoped_private_token";
  get("github-token").events.input();
  get("check-auth").events.click();
  await tick();
  assert.equal(get("auth-status").dataset.kind,"success");
  get("publish-consent").checked=true;
  get("publish-consent").events.change();
  assert.equal(get("publish-button").disabled,false);
  get("publish-button").events.click();
  await tick();
  await tick();
  assert.equal(blobNumber,2);
  assert.ok(calls.some(x=>x.path==="repos/"+OWNER+"/git/refs"));
  assert.ok(!calls.some(x=>x.path.includes("pulls")));
  assert.ok(!calls.some(x=>x.path.includes(".github/workflows")));
  assert.ok(get("upload-progress").children.length>=2);
  assert.ok(!JSON.stringify(calls).includes("github_pat_test_scoped_private_token"));
  assert.ok(!js.includes("localStorage")&&!js.includes("sessionStorage"));
  assert.ok(html.includes("connect-src https://api.github.com 'self'"));
  assert.ok(html.includes("type=\"password\""));
  assert.equal(get("check-auth").textContent,"인증 해제");
  assert.equal(get("pgn-file").value,"");
  console.log("Upload portal passed: scoped token, two blobs, PR-free Git ref.");
})().catch(error=>{
  console.error(error);
  process.exitCode=1;
});
