import numpy as np
import pandas as pd

import dash
from dash.dependencies import Input, Output, State, MATCH, ALL
import dash_core_components as dcc
import dash_html_components as html
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import dash_table
import dash_table.FormatTemplate as FormatTemplate
from dash_table.Format import Format, Scheme, Sign, Symbol

import plotly.graph_objs as go

from threading import Thread
import queue
import serial
import serial.tools.list_ports

import time
from pathlib import Path
import json
import sqlite3
from datetime import datetime

# globals... yuk
FILE_DIR = ''
APP_ID = 'serial_data'
Q = queue.Queue()
SERIAL_THREAD = None

class SerialThread(Thread):

    def __init__(self, port, baud=115200):
        super().__init__()
        self.port = port
        self._isRunning = True
        self.ser_obj = serial.Serial(port=port,
                                     baudrate=baud,
                                     parity=serial.PARITY_NONE,
                                     stopbits=serial.STOPBITS_ONE,
                                     timeout=None)

    def run(self):
        while self._isRunning:
            try:
                while self.ser_obj.in_waiting > 2:
                    try:
                        line = self.ser_obj.readline()
                        split_line = line.strip().decode("utf-8")
                        Q.put(split_line)
                    except:
                        continue
            except:
                continue


    def stop(self):
        self._isRunning = False
        time.sleep(0.25)
        self.ser_obj.close()
        return None


# layout
layout = dbc.Container([
    dbc.Row(
        dbc.Col([
            dcc.Store(id=f'{APP_ID}_store'),
            dcc.Interval(id=f'{APP_ID}_interval',
                         interval=2000,
                         n_intervals=0,
                         disabled=True),
            html.H2('Serial Data Plotter'),
            html.P('This tests plotting data from serial (arduino) using a background thread to collect the data and send it to a queue.  '
                   'Data is retrieved from the queue and stored in the browser as well as written to a file')
        ])
    ),
    dbc.Row([
        dbc.Col(
            dbc.FormGroup([
                dbc.Button('COM Ports (refresh)', id=f'{APP_ID}_com_button'),
                dcc.Dropdown(id=f'{APP_ID}_com_dropdown',
                             placeholder='Select COM port',
                             options=[],
                             multi=False),
                dbc.Textarea(id=f'{APP_ID}_com_desc_label', disabled=True )
            ]),
            width=4
        ),
        dbc.Col(
            dbc.FormGroup([
                dbc.Label('Headers'),
                dbc.Button('Initialize Headers', id=f'{APP_ID}_init_header_button', block=True),
                dash_table.DataTable(
                    id=f'{APP_ID}_header_dt',
                    columns=[
                        {"name": 'Position', "id": 'pos', "type": 'numeric', 'editable': False},
                        {"name": 'Name', "id": 'name', "type": 'text', 'editable': False},
                        {"name": 'Format', "id": 'fmt', "type": 'text', "presentation": 'dropdown'}
                             ],
                    data=None,
                    editable=True,
                    row_deletable=False,
                    dropdown={
                        'fmt': {
                            'options': [
                                {'label': i, 'value': i} for i in ['text', 'real', 'integer']
                            ],
                        },
                    }
                ),
            ]),
            width=4
        ),
    ]),
    dbc.Row(
        dbc.Col([
                dbc.Toast(
                    children=[],
                    id=f'{APP_ID}_header_toast',
                    header="Initialize Headers",
                    icon="danger",
                    dismissable=True,
                    is_open=False
                ),
        ],
            width="auto"
        ),
    ),
    dbc.Row([
        dbc.Col(
            dbc.FormGroup([
                dbc.Label('Filename'),
                dbc.Input(placeholder='filename',
                          id=f'{APP_ID}_filename_input',
                          type='text',
                          value=f'data/my_data_{datetime.now().strftime("%m.%d.%Y.%H.%M.%S")}.db')
            ])
        )
    ]),
    dbc.ButtonGroup([
        dbc.Button('Start', id=f'{APP_ID}_start_button', n_clicks=0, disabled=True, size='lg', color='secondary'),
        dbc.Button('Stop', id=f'{APP_ID}_stop_button', n_clicks=0, disabled=True, size='lg', color='secondary'),
        dbc.Button('Clear', id=f'{APP_ID}_clear_button', n_clicks=0, disabled=True, size='lg'),
        dbc.Button('Download Data', id=f'{APP_ID}_download_button', n_clicks=0, disabled=True, size='lg'),
    ],
        className='mt-2 mb-2'
    ),
    html.H2('Data Readouts'),
    dcc.Dropdown(
        id=f'{APP_ID}_readouts_dropdown',
        multi=True,
        options=[],
        value=None
    ),
    dbc.CardDeck(
        id=f'{APP_ID}_readouts_card_deck'
    ),

    html.H2('Data Plots', className='mt-2 mb-1'),
    dbc.ButtonGroup([
        dbc.Button("Hide / Show Plot Definition", id=f'{APP_ID}_plot_dt_collapse_button'),
        dbc.Button("Add Figure / Readout", id=f'{APP_ID}_add_figure_button'),
    ]),
    dbc.Collapse(
        id=f'{APP_ID}_plot_dt_collapse',
        children=[
            dash_table.DataTable(
                id=f'{APP_ID}_figure_dt',
                columns=[
                    {"name": 'Name', "id": 'name', 'type': 'text'},
                    {"name": 'X data', "id": 'x_data', 'type': 'text', 'presentation': 'dropdown'},
                    {"name": 'Y data', "id": 'y_data', 'type': 'text', 'presentation': 'dropdown'},
                    {"name": 'Width (px)', "id": 'width', 'type': 'numeric'},
                ],
                data=[],
                row_deletable=True,
                editable=True,
            ),
        ]
    ),
    # todo convert figure datatable to div with 2 select boxes (X, y (multi=true))

    html.Div(
        id=f'{APP_ID}_figure_div'
    ),
])


def add_dash(app):

    @app.callback(
        [Output(f'{APP_ID}_header_dt', 'data'),
         Output(f'{APP_ID}_header_toast', 'children'),
         Output(f'{APP_ID}_header_toast', 'is_open'),
         ],
        [Input(f'{APP_ID}_init_header_button', 'n_clicks')],
        [State(f'{APP_ID}_com_dropdown', 'value')]
    )
    def serial_data_init_header(n_clicks, com):
        if n_clicks is None or com is None:
            raise PreventUpdate

        baud = 115200
        try:
            ser_obj = serial.Serial(port=com,
                                    baudrate=baud,
                                    parity=serial.PARITY_NONE,
                                    stopbits=serial.STOPBITS_ONE,
                                    timeout=10)
            split_line = '_'
            while split_line[0] != '{':
                line = ser_obj.readline()
                split_line = line.strip().decode("utf-8")

            split_line = line.strip().decode("utf-8")
            jdic = json.loads(split_line)
            data = [{'pos': i, 'name': k} for i, k in enumerate(jdic.keys())]
            for i, k in enumerate(jdic.keys()):

                t = type(jdic[k])
                if t is int:
                    data[i].update({'fmt': 'integer'})
                if t is float:
                    data[i].update({'fmt': 'real'})
                else:
                    data[i].update({'fmt': 'text'})

            ser_obj.close()
            return data, '', False
        except Exception as e:

            return [{}], html.P(str(e)), True
        return data, '', False


    @app.callback(
        Output(f'{APP_ID}_com_dropdown', 'options'),
        [Input(f'{APP_ID}_com_button', 'n_clicks')]
    )
    def serial_data_refresh_com_ports(n_clicks):
        if n_clicks is None:
            raise PreventUpdate
        ports = [{'label': comport.device, 'value': comport.device} for comport in serial.tools.list_ports.comports()]
        return ports


    @app.callback(
        Output(f'{APP_ID}_com_desc_label', 'value'),
        [Input(f'{APP_ID}_com_dropdown', 'value')]
    )
    def serial_data_com_desc(com):
        if com is None:
            raise PreventUpdate
        ports = [comport.device for comport in serial.tools.list_ports.comports()]
        idx = ports.index(com)
        descs = [comport.description for comport in serial.tools.list_ports.comports()]
        return descs[idx]

    @app.callback(
        Output(f'{APP_ID}_plot_dt_collapse', "is_open"),
        Input(f'{APP_ID}_plot_dt_collapse_button', "n_clicks"),
        State(f'{APP_ID}_plot_dt_collapse', "is_open"),
    )
    def serial_data_plot_collapse(n, is_open):
        if n:
            return not is_open
        return is_open

    @app.callback(
        Output(f'{APP_ID}_figure_dt', 'data'),
        Output(f'{APP_ID}_figure_dt', 'dropdown'),
        Output(f'{APP_ID}_figure_div', 'children'),
        Input(f'{APP_ID}_add_figure_button', 'n_clicks'),
        Input(f'{APP_ID}_header_dt', 'data'),
        Input(f'{APP_ID}_figure_dt', 'data'),
        State(f'{APP_ID}_figure_div', 'children')
    )
    def serial_data_figure_dt(n_clicks, header_data, data, figures):
        # circular callback

        ctx = dash.callback_context
        if not ctx.triggered or header_data is None:
            raise PreventUpdate

        if figures is None:
            figures = []

        df_header = pd.DataFrame(header_data)
        df_header = df_header.dropna(axis=0, how='any')
        if df_header.empty:
            return [{}], {}, []

        dropdown = {
            'x_data': {
                'options':
                    [{'label': 'index', 'value': 'index'}] +
                    [
                        {'label': name, 'value': name} for name in df_header['name']
                    ],
            },
            'y_data': {
                'options':
                    [{'label': 'index', 'value': 'index'}] +
                    [
                        {'label': name, 'value': name} for name in df_header['name']
                    ],
            },
        }

        # add row (button press)
        # todo force index to be unique
        if ctx.triggered[0]['prop_id'].split('.')[0] == f'{APP_ID}_add_figure_button':

            if len(data) > 0:
                nxt = [n for n in range(1, len(data) + 2) if n not in [int(d['name']) for d in data]][0]
            else:
                nxt = 1
            data.append(
                {
                    'name': f'{nxt:d}',
                    'x_data': 'index',
                    'y_data': df_header['name'].values[-1],
                    'width': 400
                 }
            )

            fig = go.Figure()
            fig.update_layout(title=data[-1]['name'])
            fig.update_xaxes(title=data[-1]['x_data'])
            fig.update_yaxes(title=data[-1]['y_data'])
            ch = dcc.Graph(
                id={'type': f'{APP_ID}_plot_graph', 'index': data[-1]['name']},
                figure=fig
            )
            figures.append(ch)

            return data, dropdown, figures

        # header data changed
        if ctx.triggered[0]['prop_id'].split('.')[0] == f'{APP_ID}_header_dt':
            if data is None:
                data.append({'name': 1, 'x_data': 'index', 'y_data': df_header['name'].values[-1]})
            elif len(data) == 0:
                data.append({'name': 1, 'x_data': 'index', 'y_data': df_header['name'].values[-1]})

            return data, dropdown, figures

        # figure_dt data changed
        # todo force index to be unique
        if ctx.triggered[0]['prop_id'].split('.')[0] == f'{APP_ID}_figure_dt':

            # loop through data and create figures
            figures = []
            for i, d in enumerate(data):
                if 'name' not in d.keys():
                    d['name'] = f'{i}'
                if 'x_data' not in d.keys():
                    d['x_data'] = 'index'
                if 'y_data' not in d.keys():
                    d['y_data'] = df_header['name'].values[-1]

                fig = go.Figure()
                fig.update_layout(title=d['name'])
                fig.update_xaxes(title=d['x_data'])
                fig.update_yaxes(title=d['y_data'])
                ch = dcc.Graph(
                    id={'type': f'{APP_ID}_figures', 'index': d['name']},
                    figure=fig
                )
                figures.append(ch)
            return data, dropdown, figures


    @app.callback(
        [
            Output(f'{APP_ID}_interval', 'disabled'),
            Output(f'{APP_ID}_start_button', 'disabled'),
            Output(f'{APP_ID}_start_button', 'color'),
            Output(f'{APP_ID}_stop_button', 'disabled'),
            Output(f'{APP_ID}_stop_button', 'color'),
            Output(f'{APP_ID}_clear_button', 'disabled'),
            Output(f'{APP_ID}_clear_button', 'color'),
            Output(f'{APP_ID}_filename_input', 'disabled'),
            Output(f'{APP_ID}_filename_input', 'value'),
            Output(f'{APP_ID}_header_dt', 'editable'),
            Output(f'{APP_ID}_store', 'clear_data'),
         ],
        [
            Input(f'{APP_ID}_start_button', 'n_clicks'),
            Input(f'{APP_ID}_stop_button', 'n_clicks'),
            Input(f'{APP_ID}_clear_button', 'n_clicks'),
            Input(f'{APP_ID}_header_dt', 'data'),
         ],
        [
            State(f'{APP_ID}_com_dropdown', 'value'),
            State(f'{APP_ID}_filename_input', 'value'),
            State(f'{APP_ID}_header_dt', 'data')
         ]
    )
    def serial_data_start_stop(n_start, n_stop, n_clear, hdr_data, port, filename, data_header):
        global SERIAL_THREAD
        global Q

        ctx = dash.callback_context
        if any([n_start is None, n_stop is None, port is None, hdr_data is None, n_clear is None]):
            raise PreventUpdate
        if pd.DataFrame(hdr_data).empty:
            raise PreventUpdate

        df_hdr = pd.DataFrame(data_header).sort_values('pos')
        df_hdr['name'] = df_hdr['name'].fillna(df_hdr['pos'].astype(str))
        headers = df_hdr['name'].tolist()

        trig = ctx.triggered[0]['prop_id'].split('.')[0]
        if trig == f'{APP_ID}_header_dt':
            if len(data_header[0].keys()) == 3 and ~df_hdr.isnull().values.any():
                return True, False, 'success', True, 'secondary', True, 'secondary', False, filename, True, False
            else:
                return True, True, 'secondary', True, 'secondary', True, 'secondary', False, filename, True, False


        if trig == f'{APP_ID}_start_button':
            print(f'starting: {filename}')
            if filename is None or filename == '':
                filename = f'data/my_data_{datetime.now().strftime("%m.%d.%Y.%H.%M.%S")}.db'
            if (Path(FILE_DIR) / filename).exists():
                clear = False
            else:
                clear = True
            SERIAL_THREAD = SerialThread(port, baud=115200)
            SERIAL_THREAD.start()
            return False, True, 'secondary', False, 'danger', True, 'secondary', True, filename, False, clear

        if trig == f'{APP_ID}_stop_button':
            print('stopping')
            SERIAL_THREAD.stop()
            with Q.mutex:
                Q.queue.clear()
            return True, False, 'success', True, 'secondary', False, 'warning', False, filename, True, False

        if trig == f'{APP_ID}_clear_button':
            print('clearing')
            filename = f'data/my_data_{datetime.now().strftime("%m.%d.%Y.%H.%M.%S")}.db'
            return True, False, 'success', True, 'secondary', True, 'secondary', False, filename, True, True


    @app.callback(
        Output(f'{APP_ID}_store', 'data'),
        [Input(f'{APP_ID}_interval', 'n_intervals')],
        [State(f'{APP_ID}_interval', 'disabled'),
         State(f'{APP_ID}_store', 'data'),
         State(f'{APP_ID}_filename_input', 'value'),
         State(f'{APP_ID}_header_dt', 'data')
         ]
    )
    def serial_data_update_store(n_intervals, disabled, data, filename, data_header):
        global Q
        # get data from queue
        if disabled is not None and not disabled:
            new_data = []
            while not Q.empty():
                new_data_dic = json.loads(Q.get())
                new_data.append(tuple((new_data_dic[c["name"]] for c in data_header if c["name"] in new_data_dic.keys())))

            conn = sqlite3.connect(FILE_DIR + filename)
            c = conn.cursor()

            c.execute(''' SELECT count(name) FROM sqlite_master WHERE type='table' AND name='my_data' ''')
            if c.fetchone()[0] == 1:
                c.executemany(f'INSERT INTO my_data VALUES ({(",".join(["?"] * len(data_header)) )})', new_data)
                conn.commit()
                last_row_id = c.execute("SELECT COUNT() FROM my_data").fetchone()[0]
                conn.close()
            else:
                c.execute(
                    f'''CREATE TABLE my_data
                    (''' + ', '.join([f'{hdr["name"]} {hdr["fmt"]}' for hdr in data_header])
                    + ')'
                )
                c.executemany(f'INSERT INTO my_data VALUES ({(",".join(["?"] * len(data_header)) )})', new_data)
                conn.commit()
                last_row_id = c.execute("SELECT COUNT() FROM my_data").fetchone()[0]
                conn.close()
            return last_row_id


    @app.callback(
        Output(f'{APP_ID}_readouts_dropdown', 'options'),
        Input(f'{APP_ID}_header_dt', 'data')
    )
    def serial_data_readout_options(hdr_data):
        if hdr_data is None:
            raise PreventUpdate
        if pd.DataFrame(hdr_data).empty:
            raise PreventUpdate
        print(hdr_data)
        df_hdr = pd.DataFrame(hdr_data).sort_values('pos')
        df_hdr['name'] = df_hdr['name'].fillna(df_hdr['pos'].astype(str))
        headers = df_hdr['name'].tolist()
        options = [{'label': c, 'value': c} for c in headers]
        return options

    @app.callback(
        Output(f'{APP_ID}_readouts_card_deck', 'children'),
        Output(f'{APP_ID}_readouts_dropdown', 'value'),
        Input(f'{APP_ID}_readouts_card_deck', 'children'),
        Input(f'{APP_ID}_readouts_dropdown', 'value'),
    )
    def serial_data_create_readouts(cards, selected):

        ctx = dash.callback_context
        input_id = ctx.triggered[0]["prop_id"].split(".")[0]
        if input_id == f'{APP_ID}_readouts_card_deck':
            # collect ids of toasts to updated selected items in dropdown
            selected = []
            for card in cards:
                selected.append(card['id']['index'])
        else:
            # collect selected to create toasts
            cards = []
            if selected is not None:
                for s in selected:
                    cards.append(
                        dbc.Card(
                            id={'type': f'{APP_ID}_readout_card', 'index': s},
                            children=[
                                dbc.CardHeader(s),
                            ]
                        )
                    )
        return cards, selected



    @app.callback(
        Output({'type': f'{APP_ID}_readout_card', 'index': ALL}, 'children'),
        Output({'type': f'{APP_ID}_figures', 'index': ALL}, 'figure'),
        Input(f'{APP_ID}_store', 'modified_timestamp'),
        State(f'{APP_ID}_store', 'data'),
        State(f'{APP_ID}_filename_input', 'value'),
        State(f'{APP_ID}_figure_dt', 'data')
    )
    def serial_data_update_readouts(ts, data, filename, fig_dt_data):
        if any([v is None for v in [ts, data]]):
            raise PreventUpdate

        conn = sqlite3.connect(FILE_DIR + filename)
        cur = conn.cursor()
        n_estimate = cur.execute("SELECT COUNT() FROM my_data").fetchone()[0]
        n_int = n_estimate // 10000 + 1
        query = f'SELECT * FROM my_data WHERE ROWID % {n_int} = 0'
        df = pd.read_sql(query, conn)
        conn.close()

        card_chs = []
        for ccb in dash.callback_context.outputs_list[0]:
            y = df[ccb['id']['index']].iloc[-1]
            ch = [
                dbc.CardHeader(ccb['id']['index']),
                dbc.CardBody(
                    dbc.ListGroup([
                        dbc.ListGroupItem(html.H3(f"{y:0.3g}"), color='info'),
                    ]),
                )
                ]
            card_chs.append(ch)

        df_fig = pd.DataFrame(fig_dt_data).dropna(axis=0, how='any')
        figs = []
        if not df_fig.empty:
            for fcb in dash.callback_context.outputs_list[1]:
                s_fig = df_fig.loc[df_fig['name'].astype(str) == fcb['id']['index']].iloc[0, :]
                x_data = s_fig['x_data']
                y_data = s_fig['y_data']
                if x_data == 'index':
                    x = df.index
                else:
                    x = df[x_data]
                if y_data == 'index':
                    y = df.index
                else:
                    y = df[y_data]

                fig = go.Figure()
                fig.update_xaxes(title=x_data)
                fig.update_yaxes(title=y_data)
                fig.update_layout(margin={'l': 20, 'r': 20, 't': 0, 'b': 20})
                fig.add_trace(
                    go.Scatter(
                        x=x,
                        y=y,
                        showlegend=False
                    )
                )
                figs.append(fig)

        return card_chs, figs

    return app


if __name__ == '__main__':
    # app
    external_stylesheets = [
        dbc.themes.BOOTSTRAP,
    ]
    app = dash.Dash(__name__, external_stylesheets=external_stylesheets)
    app.layout = layout
    app = add_dash(app)

    app.run_server(debug=True)