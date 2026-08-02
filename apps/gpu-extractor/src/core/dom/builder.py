# pyright: reportAttributeAccessIssue=false
from pydantic import BaseModel, Field
from typing import List, Optional

import proto.prism.v1.dom_pb2 as dom_pb2


class ProvenanceModel(BaseModel):
    page_number: int
    bounding_box: List[float] = Field(..., min_length=4, max_length=4)


class NodeModel(BaseModel):
    id: str
    type: int  # 1=TEXT, 2=TABLE, 3=IMAGE
    content: str
    provenance: ProvenanceModel
    children: List["NodeModel"] = []


class DOMBuilder:
    def __init__(self):
        self.nodes: List[NodeModel] = []
        self._current_section: Optional[NodeModel] = None

    def add_element(self, element: dict):
        type_str = element.get("type", "TEXT")
        if type_str == "TABLE":
            node_type = dom_pb2.NODE_TYPE_TABLE
        elif type_str == "IMAGE":
            node_type = dom_pb2.NODE_TYPE_IMAGE
        elif type_str == "KEY_VALUE":
            node_type = dom_pb2.NODE_TYPE_KEY_VALUE
        elif type_str == "FORM":
            node_type = dom_pb2.NODE_TYPE_FORM
        elif type_str == "SECTION_HEADER":
            node_type = dom_pb2.NODE_TYPE_SECTION_HEADER
        elif type_str == "TITLE":
            node_type = dom_pb2.NODE_TYPE_TITLE
        elif type_str == "CHECKBOX":
            node_type = dom_pb2.NODE_TYPE_CHECKBOX
        elif type_str == "CODE":
            node_type = dom_pb2.NODE_TYPE_CODE
        else:
            node_type = dom_pb2.NODE_TYPE_TEXT

        node = NodeModel(
            id=f"node_p{element.get('page', 1)}_{len(self.nodes) + 1}",
            type=node_type,
            content=element.get("content") or "",
            provenance=ProvenanceModel(
                page_number=element.get("page", 1), bounding_box=element.get("bbox", [0.0, 0.0, 0.0, 0.0])
            ),
        )

        if node.type in (dom_pb2.NODE_TYPE_SECTION_HEADER, dom_pb2.NODE_TYPE_TITLE):
            self.nodes.append(node)
            self._current_section = node
        else:
            if self._current_section is not None:
                self._current_section.children.append(node)
            else:
                self.nodes.append(node)

    def to_protobuf(self) -> dom_pb2.DocumentDOM:
        doc = dom_pb2.DocumentDOM()

        def _convert_node(pydantic_node: NodeModel) -> dom_pb2.Node:
            pb_node = dom_pb2.Node(
                id=pydantic_node.id,
                type=pydantic_node.type,
                content=pydantic_node.content,
            )
            pb_node.provenance.page_number = pydantic_node.provenance.page_number
            pb_node.provenance.bounding_box.extend(
                pydantic_node.provenance.bounding_box
            )

            for child in pydantic_node.children:
                pb_child = _convert_node(child)
                pb_node.children.append(pb_child)

            return pb_node

        for n in self.nodes:
            doc.nodes.append(_convert_node(n))

        return doc
