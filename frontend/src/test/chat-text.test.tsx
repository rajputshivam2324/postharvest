import { render, screen } from '@testing-library/react';
import { ChatText } from '../components/Chat';

describe('ChatText', () => {
  it('renders dash lines as a list and keeps markup inert', () => {
    const { container } = render(
      <ChatText
        text={
          'Two batches need a look.\n- Batch A is high risk\n- Batch B has no readings\n<img src=x onerror=alert(1)>'
        }
      />,
    );
    expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Batch A is high risk',
      'Batch B has no readings',
    ]);
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText(/<img src=x/)).toBeInTheDocument();
  });
});
