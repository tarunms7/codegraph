import { AuthService, createToken } from './auth';
import { IUser } from './types';

export class App {
    private auth: AuthService;

    constructor() {
        this.auth = new AuthService({ secret: 'app-secret', expiresIn: 3600 });
    }

    start(): void {
        const user: IUser = { name: 'admin', email: 'admin@admin.com' };
        const token = createToken(user);
        const authenticated = this.auth.authenticate(token);
        console.log('Started with user:', authenticated.name);
    }
}
