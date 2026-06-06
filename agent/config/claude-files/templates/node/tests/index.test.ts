import { main } from '../src/index';

describe('main', () => {
  it('should run without errors', async () => {
    const consoleSpy = jest.spyOn(console, 'log').mockImplementation();

    await main();

    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });
});
