import { AuthService, createToken } from '../auth';

describe('AuthService', () => {
    const config = { secret: 'test-secret', expiresIn: 3600 };
    const service = new AuthService(config);

    it('should authenticate', () => {
        const user = { name: 'Alice', email: 'alice@example.com' };
        const token = createToken(user);
        const result = service.authenticate(token);
        expect(result.name).toBe('Alice');
    });

    it('should authorize admin users', () => {
        const admin = { name: 'Admin', email: 'admin@admin.com' };
        expect(service.authorize(admin, 'write')).toBe(true);
    });
});
