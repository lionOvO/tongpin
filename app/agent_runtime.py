"""Shared, invocation-local LangGraph scheduling; business adapters own permissions."""
from typing import TypedDict
from langgraph.graph import StateGraph, START, END


class RunState(TypedDict):
    messages: list[dict]
    calls: list[dict]
    output: dict | None


def invoke_tool_graph(model, execute, messages):
    graph = StateGraph(RunState)
    graph.add_node('model', model); graph.add_node('tools', execute)
    graph.add_edge(START, 'model')
    graph.add_conditional_edges('model', lambda s: END if s['output'] is not None else 'tools' if s['calls'] else 'model')
    graph.add_edge('tools', 'model')
    return graph.compile().invoke({'messages': messages, 'calls': [], 'output': None},
        {'recursion_limit': 20, 'callbacks': []})['output']
