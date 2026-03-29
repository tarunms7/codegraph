import React from 'react';
import { fetchItems } from './api';

export class App extends React.Component {
    state = { items: [] as any[] };

    componentDidMount() {
        fetchItems().then((response) => {
            this.setState({ items: response.data });
        });
    }

    render() {
        return (
            <div>
                <h1>Items</h1>
                <ul>
                    {this.state.items.map((item: any) => (
                        <li key={item.id}>{item.name}</li>
                    ))}
                </ul>
            </div>
        );
    }
}

export function AppWrapper(): JSX.Element {
    return <App />;
}
