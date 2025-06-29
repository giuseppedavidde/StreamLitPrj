import plotly.graph_objs as go
import plotly.subplots as sp
import pandas as pd
import numpy as np
import streamlit as st


def create_plot(x, y, name_trace, name_graph, overlap, n_traces):
    fig = go.Figure()
    if overlap:
        for i, y_list in enumerate(y):
            fig.add_trace(
                go.Scatter(x=x, y=y_list, mode="lines+markers", name=f"{name_trace[i]}")
            )
    else:
        fig.add_trace(go.Scatter(x=x, y=y, mode="lines+markers", name=f"{name_trace}"))
    fig.update_layout(
        title=f"{name_graph}",
        xaxis_title="",
        yaxis_title="",
        legend_title="Legenda",
        hovermode="x",
    )
    st.plotly_chart(fig)
    return fig


def create_subplot(x, y, y1, name_graph, name_trace, name_trace1, overlap, n_graphs):
    subplots = sp.make_subplots(rows=1, cols=n_graphs)
    if overlap:
        for i, y_list in enumerate(y):
            subplots.add_trace(
                go.Scatter(
                    x=x, y=y_list, mode="lines+markers", name=f"{name_trace[i]}"
                ),
                row=1,
                col=1,
            )
        for k, y1_list in enumerate(y1):
            subplots.add_trace(
                go.Scatter(
                    x=x, y=y1_list, mode="lines+markers", name=f"{name_trace1[k]}"
                ),
                row=1,
                col=2,
            )
    else:
        subplots.add_trace(
            go.Scatter(x=x, y=y, mode="lines+markers", name=f"{name_trace}"),
            row=1,
            col=1,
        )
    subplots.update_layout(
        title=f"{name_graph}",
        xaxis_title="",
        yaxis_title="",
        legend_title="Legenda",
        hovermode="x",
    )
    st.plotly_chart(subplots)
    return subplots


def show_table(df):
    st.dataframe(df)
