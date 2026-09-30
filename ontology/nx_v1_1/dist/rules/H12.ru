PREFIX nx: <https://cncgaide.org/ontology/nx/1.1#>
PREFIX cg: <https://cncgaide.org/ontology/nx/1.1/pipeline#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX dcterms: <http://purl.org/dc/terms/>

INSERT {
  GRAPH <{OUT}> {
    ?verdict a cg:Verdict ;
      cg:heuristic cg:H12 ;
      cg:target ?rel ;
      cg:targetA ?a ;
      cg:targetB ?b ;
      cg:partOf ?part ;
      cg:outcome ?outcome ;
      cg:usedThreshold [ cg:threshold cg:t_hole_web ; cg:value ?t_hole_web ] ;
      cg:value [ a cg:Value ; cg:name "axisSpacing" ; cg:value ?v_axisSpacing ] ;
      cg:value [ a cg:Value ; cg:name "entryDiameterA" ; cg:value ?v_entryDiameterA ] ;
      cg:value [ a cg:Value ; cg:name "entryDiameterB" ; cg:value ?v_entryDiameterB ] ;
      cg:value [ a cg:Value ; cg:name "web" ; cg:value ?v_web ] ;
      cg:scope "pair" .
  }
}
WHERE {
  GRAPH <{ONTOLOGY}> { cg:H12 cg:appliesTo ?clsA , ?clsB . cg:t_hole_web cg:value ?t_hole_web . }
  GRAPH <{FACTS}> {
    ?rel a cg:FeatureRelation ; cg:relationType cg:HOLE_SPACING ; cg:from ?a ; cg:to ?b ; cg:partOf ?part .
    ?a a ?clsA . ?b a ?clsB .
  }
  FILTER NOT EXISTS {
    GRAPH <{ONTOLOGY}> { cg:H12 cg:requires ?rq . ?rq cg:onClass ?clsA ; cg:attribute ?ra }
    FILTER NOT EXISTS { GRAPH <{FACTS}> { ?a ?ra ?rv } }
  }
  FILTER NOT EXISTS {
    GRAPH <{ONTOLOGY}> { cg:H12 cg:requires ?rq . ?rq cg:onClass ?clsB ; cg:attribute ?ra }
    FILTER NOT EXISTS { GRAPH <{FACTS}> { ?b ?ra ?rv } }
  }
  GRAPH <{ONTOLOGY}> { ?clsA cg:entryDiameterAttribute ?dpA . ?clsB cg:entryDiameterAttribute ?dpB }
  GRAPH <{FACTS}> { ?rel cg:axisSpacing ?v_axisSpacing . ?a ?dpA ?v_entryDiameterA . ?b ?dpB ?v_entryDiameterB }
  BIND(?v_axisSpacing - (?v_entryDiameterA + ?v_entryDiameterB) / 2 AS ?v_web)
  BIND(IF(?v_web >= ?t_hole_web, cg:PASS, cg:FAIL) AS ?outcome)
  BIND(IRI(CONCAT(STR(?rel), "/verdict/H12")) AS ?verdict)
}
